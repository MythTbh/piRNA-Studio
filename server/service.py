"""Framework-independent API for the local piRNA Studio workspace."""

import io
import json
import mimetypes
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from .references import ReferenceCache, CATALOG, reference
from .exports import export
from .store import ROOT, Store

from .uploads import MultipartReader, body_size

MAX_BODY = 4 * 1024 * 1024 * 1024
UPLOAD_LIMIT_ERROR = "The upload limit is 4 GiB total per request"


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def serialized(payload, status=200):
    return (
        status,
        {"Content-Type": "application/json; charset=utf-8"},
        json.dumps(payload, allow_nan=False).encode(),
    )


def stage_upload(body, content_type, staged):
    if (
        not content_type.startswith("multipart/form-data")
        or "\r" in content_type
        or "\n" in content_type
    ):
        raise APIError(415, "Send files and config as multipart/form-data.")
    form = MultipartReader(body, content_type)
    inputs = staged / "inputs"
    inputs.mkdir()
    uploaded = {}
    raw_config = None
    while not form.finished:
        part = form.headers()
        name = part.get_param("name", header="content-disposition")
        if name == "config":
            if raw_config is not None:
                raise ValueError("Send one config per request")
            config_body = io.BytesIO()
            form.copy_to(config_body, limit=1024 * 1024)
            raw_config = json.loads(config_body.getvalue())
        elif name == "files":
            filename = part.get_filename() or ""
            if (
                filename in ("", ".", "..")
                or "/" in filename
                or "\\" in filename
                or any(ord(ch) < 32 for ch in filename)
                or len(filename.encode()) > 200
                or filename in uploaded
            ):
                raise ValueError("Upload each file with a distinct, plain filename")
            path = inputs / filename
            with path.open("xb") as handle:
                form.copy_to(handle)
            uploaded[filename] = path
        else:
            raise ValueError("Unknown upload field")
    if not isinstance(raw_config, dict) or not isinstance(
        raw_config.get("samples"), list
    ):
        raise ValueError("Provide a configuration with a samples array")

    def resolve(name):
        if name not in uploaded:
            raise ValueError(f"Select the input file {str(name)[:150]!r}")
        return str(uploaded[name].relative_to(staged))

    samples = []
    for row in raw_config["samples"]:
        if not isinstance(row, dict):
            raise ValueError("Each sample needs a sample identifier and FASTQ file")
        sample = {
            key: str(row.get(key, "")).strip()
            for key in ("sample_id", "condition", "replicate", "library_kit")
        }
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", sample["sample_id"]):
            raise ValueError(
                "Sample IDs must start with a letter or digit and contain only letters, digits, periods, hyphens, or underscores"
            )
        if row.get("adapter"):
            sample["adapter"] = str(row["adapter"])
        sample["fastq_path"] = resolve(row.get("fastq_path"))
        sample["layout"] = str(row.get("layout") or ("paired" if row.get("fastq_r2_path") else "single"))
        if row.get("fastq_r2_path"):
            sample["fastq_r2_path"] = resolve(row["fastq_r2_path"])
        samples.append(sample)
    params = raw_config.get("params", {})
    if not isinstance(params, dict) or any(
        not isinstance(v, (bool, int, float, str)) for v in params.values()
    ):
        raise ValueError("Provide parameter names and scalar values")
    allowed = {
        "adapter_mode",
        "length_filter",
        "min_length",
        "max_length",
        "min_cluster_size",
        "max_gap",
        "min_loci",
        "support",
        "count_mode",
        "min_total_count",
        "backend",
        "de_method",
        "protrac_profile",
    }
    if set(params) - allowed:
        raise ValueError(
            "Unknown parameter: " + ", ".join(sorted(set(params) - allowed))
        )
    config = {
        "samples": samples,
        "genome": "" if raw_config.get("reference_genome") else resolve(raw_config.get("genome")),
        "params": params,
    }
    if raw_config.get("reference_genome"):
        reference(raw_config["reference_genome"])
        config["reference_genome"] = raw_config["reference_genome"]
    if raw_config.get("reference"):
        config["reference"] = resolve(raw_config["reference"])
    if raw_config.get("repeats"):
        config["repeats"] = resolve(raw_config["repeats"])
    if raw_config.get("ncrna"):
        refs = raw_config["ncrna"]
        if not isinstance(refs, dict) or not set(refs) <= {
            "rRNA",
            "tRNA",
            "snRNA",
            "miRNA",
        }:
            raise ValueError(
                "Use rRNA, tRNA, snRNA, or miRNA for ncRNA reference classes"
            )
        config["ncrna"] = {cls: resolve(filename) for cls, filename in refs.items()}
    return config


def absolute_inputs(config, staged):
    result = {**config, "genome": str(staged / config["genome"])}
    result["samples"] = [
        {**s, "fastq_path": str(staged / s["fastq_path"])} for s in config["samples"]
    ]
    for sample in result["samples"]:
        if sample.get("fastq_r2_path"):
            sample["fastq_r2_path"] = str(staged / sample["fastq_r2_path"])
    if "reference" in config:
        result["reference"] = str(staged / config["reference"])
    if "repeats" in config:
        result["repeats"] = str(staged / config["repeats"])
    if "ncrna" in config:
        result["ncrna"] = {k: str(staged / v) for k, v in config["ncrna"].items()}
    return result


class Service:
    def __init__(self, directory):
        self.store = Store(directory)
        self.web = ROOT / "web" / "dist"
        self.references = ReferenceCache(self.store.directory / "references")

    def dispatch(self, method, target, headers, body=b""):
        try:
            path = urlsplit(target)
            if method == "POST":
                origin = headers.get("origin")
                if origin and urlsplit(origin).netloc != headers.get("host"):
                    raise APIError(403, "Submit inputs from this local workspace")
                if body_size(body) > MAX_BODY:
                    raise APIError(413, UPLOAD_LIMIT_ERROR)
            if path.path == "/api/health" and method == "GET":
                return serialized(
                    {"status": "ok", "service": "piRNA Studio", "version": "1", "max_upload_bytes": MAX_BODY}
                )
            if path.path == "/api/references" and method == "GET":
                return serialized({"references": CATALOG})
            ref_match = re.fullmatch(r"/api/references/([a-z]+)", path.path)
            if ref_match and method in {"GET", "POST"}:
                key = ref_match[1]
                return serialized(self.references.prepare(key) if method == "POST" else self.references.status(key))
            if path.path in ("/api/preflight", "/api/runs") and method == "POST":
                return self._submit(path.path, headers, body)
            if path.path == "/api/runs" and method == "GET":
                return serialized({"runs": self.store.list_runs()})
            match = re.fullmatch(
                r"/api/runs/([a-f0-9]{32})/([a-z]+)(?:/([^/]+))?", path.path
            )
            if match:
                rid, action, child = match.groups()
                status = self.store.status(rid)
                if action == "cancel" and child is None and method == "POST":
                    return serialized(self.store.cancel(rid))
                if method != "GET":
                    raise APIError(405, "Use GET to read analysis results")
                if action == "status" and child is None:
                    return serialized(status)
                if status["status"] != "completed":
                    raise APIError(
                        409, "Results are available after analysis completes"
                    )
                return self._results(
                    rid,
                    action,
                    unquote(child) if child else None,
                    dict(parse_qsl(path.query)),
                )
            if path.path.startswith("/api/"):
                raise APIError(404, "Unknown API endpoint")
            if method != "GET":
                raise APIError(405, "Use GET for application assets")
            asset = (
                self.web / (unquote(path.path).lstrip("/") or "index.html")
            ).resolve()
            if not asset.is_relative_to(self.web) or not asset.is_file():
                raise APIError(404, "File not found")
            return (
                200,
                {
                    "Content-Type": mimetypes.guess_type(asset.name)[0]
                    or "application/octet-stream"
                },
                asset.read_bytes(),
            )
        except APIError as exc:
            return serialized({"error": exc.message}, exc.status)
        except KeyError:
            return serialized({"error": "Unknown run or cluster"}, 404)
        except (ValueError, TypeError, OverflowError) as exc:
            return serialized({"error": str(exc)}, 400)

    def _submit(self, path, headers, body):
        from engine.inputs import preflight

        with tempfile.TemporaryDirectory(
            dir=self.store.directory, prefix="upload-"
        ) as tmp:
            # Keep TemporaryDirectory's own path intact when the run takes ownership.
            staged = Path(tmp) / "job"
            staged.mkdir()
            try:
                config = stage_upload(body, headers.get("content-type", ""), staged)
                if config.get("reference_genome"):
                    config["genome"], config["reference_assembly"] = self.references.attach(config["reference_genome"], staged)
                checks = preflight(absolute_inputs(config, staged))
            except (ValueError, OSError, TypeError) as exc:
                checks = [
                    {
                        "name": "Inputs",
                        "severity": "error",
                        "message": str(exc),
                        "fix": "Review the sample sheet and selected files.",
                    }
                ]
            review = {
                "checks": checks,
                "blocking": any(c["severity"] == "error" for c in checks),
            }
            if path == "/api/preflight":
                return serialized(review)
            if review["blocking"]:
                return serialized(
                    {
                        **review,
                        "error": "Resolve blocking input checks before starting",
                    },
                    422,
                )
            return serialized({"run_id": self.store.submit(staged, config)}, 202)

    def _results(self, rid, action, child, q):
        run_dir = self.store.directory / rid
        if action == "clusters":
            if child is None:
                return serialized(self.store.cluster_page(rid, q))
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT payload FROM clusters WHERE run_id=? AND cluster_id=?",
                    (rid, child),
                ).fetchone()
                if row is None:
                    raise KeyError(child)
                return serialized(json.loads(row[0]))
        if child or action not in {
            "results",
            "qc",
            "tracks",
            "de",
            "validation",
            "provenance",
            "export",
        }:
            raise APIError(404, "Unknown results endpoint")
        result = json.loads((run_dir / "outputs" / "results.json").read_text())
        if action == "results":
            return serialized(result)
        if action == "qc":
            return serialized({k: result[k] for k in ("qc", "accounting")})
        if action == "tracks":
            left, right = int(q.get("start", 0)), int(q.get("end", 2**62))
            if not 0 <= left < right:
                raise ValueError("Use a valid genomic interval")
            return serialized(
                {
                    "tracks": [
                        t
                        for t in result["tracks"]
                        if (not q.get("chr") or q["chr"] == t["chr"])
                        and t["end"] > left
                        and t["start"] < right
                    ]
                }
            )
        if action == "de":
            return serialized(
                {
                    "de": [
                        row
                        for row in result["de"]
                        if not q.get("contrast") or q["contrast"] == row.get("contrast")
                    ]
                }
            )
        if action == "export":
            data, kind, filename = export(run_dir, rid, result, q.get("format", "zip"))
            return (
                200,
                {
                    "Content-Type": kind,
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
                data,
            )
        return serialized(result[action])
