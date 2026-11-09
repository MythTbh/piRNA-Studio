"""Input parsing and preflight checks. Genomic coordinates are BED0 internally."""

import csv
import gzip
import hashlib
import json
import re
import shutil
from collections import Counter
from itertools import islice
from pathlib import Path

ADAPTERS = {
    "illuminamirnaud": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
    "lexogenmirvel": "TGGAATTCTCGGGTGCCAAGG",
    "nebnextlowbias": "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
    "illuminasmallrnav15": "ATCTCGTATGCCGTCTTCTGCTTG",
    "truseq": "TGGAATTCTCGGGTGCCAAGG",
    "nebnext": "AGATCGGAAGAGCACACGTCT",
    "qiaseq": "AACTGTAGGCACCATCAAT",
    "lexogen": "TGGAATTCTCGGGTGCCAAGGAACTCCAGTCAC",
}
DEFAULTS = dict(
    adapter_mode="retain",
    length_filter="range",
    min_length=24,
    max_length=32,
    min_cluster_size=1000,
    max_gap=150,
    min_loci=5,
    support=2,
    count_mode="fractional",
    min_total_count=10,
    backend="portable",
    de_method="auto",
    protrac_profile="default",
)
DNA = re.compile(r"[ACGTN]+")
IUPAC = re.compile(r"[ACGTRYSWKMBDHVN]+")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


def open_seq(path):
    with open(path, "rb") as stream:
        compressed = stream.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rt", encoding="ascii") if compressed else open(path, encoding="ascii")


def genome(path, *, rna=False):
    seqs = {}
    with open_seq(path) as stream:
        name = None
        for raw in stream:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                header = line[1:].split()
                if not header or header[0] in seqs:
                    raise ValueError("Empty or duplicate FASTA sequence name")
                name = header[0]
                seqs[name] = []
            else:
                bases = line.upper().replace("U", "T") if rna else line.upper()
                if name is None or not IUPAC.fullmatch(bases):
                    raise ValueError("Expected valid FASTA header and nucleotide sequence")
                seqs[name].append(bases)
    if not seqs or any(not chunks for chunks in seqs.values()):
        raise ValueError("Empty FASTA sequence")
    return {name: "".join(parts) for name, parts in seqs.items()}


def write_genome(path, seqs):
    # sRNAmapper repeatedly consumes each FASTA line: cap line length to avoid quadratic copies.
    with Path(path).open("w") as stream:
        for name, bases in seqs.items():
            stream.write(f">{name}\n")
            for start in range(0, len(bases), 80):
                stream.write(bases[start : start + 80] + "\n")


def fastq_records(path):
    with open_seq(path) as stream:
        for n, header in enumerate(stream, 1):
            seq = stream.readline().rstrip("\r\n").upper().replace("U", "T")
            plus = stream.readline().rstrip("\r\n")
            qual = stream.readline().rstrip("\r\n")
            if (
                not header.startswith("@")
                or not plus.startswith("+")
                or len(qual) != len(seq)
                or not DNA.fullmatch(seq)
                or any(ord(c) < 33 or ord(c) > 126 for c in qual)
            ):
                raise ValueError(f"Malformed FASTQ record {n}")
            identity = header[1:].split()
            if not identity:
                raise ValueError(f"Missing FASTQ identifier at record {n}")
            yield identity[0], seq, qual


def fastq(path):
    for _, sequence, _ in fastq_records(path):
        yield sequence


def is_paired(sample):
    layout = sample.get("layout") or ("paired" if sample.get("fastq_r2_path") else "single")
    if layout not in {"single", "paired"}:
        raise ValueError("Choose single or paired for the sequencing layout")
    if layout == "paired" and not sample.get("fastq_r2_path"):
        raise ValueError("Paired-end samples need both R1 and R2 FASTQ files")
    if layout == "single" and sample.get("fastq_r2_path"):
        raise ValueError("Select paired-end layout when providing R2")
    if layout == "paired" and sample["fastq_path"] == sample["fastq_r2_path"]:
        raise ValueError("R1 and R2 must be different files")
    return layout == "paired"


def bed(path, seqs):
    intervals = []
    names = set()
    with open_seq(path) as stream:
        for n, line in enumerate(stream, 1):
            if not line.strip() or line.startswith(("#", "track ", "browser ")):
                continue
            fields = line.rstrip().split("\t")
            if len(fields) < 3:
                raise ValueError(f"Expected BED columns on line {n}")
            chrom = fields[0]
            start, end = map(int, fields[1:3])
            name = fields[3] if len(fields) >= 4 and fields[3] != "." else f"ref-{n}"
            if chrom not in seqs or not 0 <= start < end <= len(seqs[chrom]):
                raise ValueError(f"BED coordinates on line {n} do not fit this assembly")
            if name in names:
                name = f"{name}-line{n}"
            if name in names:
                raise ValueError(f"Duplicate BED identifier on line {n}")
            names.add(name)
            intervals.append((chrom, start, end, name))
    return intervals


def adapter(sample):
    value = str(sample.get("adapter") or sample.get("library_kit") or "truseq").strip()
    norm = re.sub(r"[^a-z0-9]", "", value.lower())
    if "truseq" in norm:
        return ADAPTERS["truseq"]
    for kit, seq in ADAPTERS.items():
        if norm.startswith(kit):
            return seq
    seq = value.upper().replace("U", "T")
    if not re.fullmatch("[ACGT]{3,128}", seq):
        raise ValueError("Choose a kit preset or supply a 3–128 base adapter")
    return seq



def adapter_positions(reads, sequence, backend):
    """Predict trimming with the same matcher as the selected analysis backend."""
    if backend == "portable":
        return [read.find(sequence) for read in reads]
    from cutadapt.adapters import BackAdapter

    matcher = BackAdapter(sequence)
    return [match.rstart if (match := matcher.match_to(read)) is not None else -1
            for read in reads]


def percentage(a, b):
    return round(100 * a / b, 3) if b else 0


def checksum(path):
    with open(path, "rb") as stream:
        return (
            hashlib.file_digest(stream, "sha256").hexdigest()
            if hasattr(hashlib, "file_digest")
            else _hash_stream(stream)
        )


def _hash_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def load_config(path):
    root = Path(path).resolve().parent
    config = json.loads(Path(path).read_text())
    if "sample_sheet" in config:
        with open(root / config["sample_sheet"], newline="") as sheet:
            config["samples"] = list(csv.DictReader(sheet))
    for key in ("genome", "reference", "repeats"):
        if config.get(key):
            config[key] = str(root / config[key])
    config["ncrna"] = {kind: str(root / file) for kind, file in config.get("ncrna", {}).items()}
    for sample in config["samples"]:
        sample["fastq_path"] = str(root / sample["fastq_path"])
        if sample.get("fastq_r2_path"):
            sample["fastq_r2_path"] = str(root / sample["fastq_r2_path"])
    return config


def preflight(config, check_tools=True):
    rows = []

    def check(name, severity, msg, fix=""):
        rows.append(dict(name=name, severity=severity, message=msg, fix=fix))

    params = {**DEFAULTS, **config.get("params", {})}
    lo, hi = params["min_length"], params["max_length"]
    integers = [
        "min_length",
        "max_length",
        "min_cluster_size",
        "max_gap",
        "min_loci",
        "support",
        "min_total_count",
    ]
    if any(type(params[k]) is not int or params[k] < 1 for k in integers) or not 10 <= lo <= hi <= 128:
        check(
            "Parameters",
            "error",
            "Invalid length range or nonpositive threshold.",
            "Use integer thresholds and lengths from 10 to 128.",
        )
        return rows
    if (
        params["backend"] not in {"portable", "protrac"}
        or params["count_mode"] not in {"fractional", "unique"}
        or params["adapter_mode"] not in {"retain", "require", "skip"}
        or params["length_filter"] not in {"range", "all"}
        or params["de_method"] not in {"auto", "pydeseq2", "descriptive"}
    ):
        check(
            "Parameters",
            "error",
            "Unknown analysis mode.",
            "Use a documented backend, counting and DE mode.",
        )
    if params["protrac_profile"] not in {"default", "clusterdb"}:
        check("proTRAC profile", "error", "Unknown caller profile.", "Choose default or clusterdb.")
    if check_tools and params["backend"] == "protrac":
        import os

        for tool in ("cutadapt", "perl"):
            if not shutil.which(tool):
                check(tool, "error", f"{tool} is missing.", "Install the supplied Conda environment.")
        for key in ("DUSTER_PL", "SRNAMAPPER_PL", "PROTRAC_PL"):
            if not Path(os.environ.get(key, "")).is_file():
                check(
                    key,
                    "error",
                    "Perl tool script could not be found.",
                    f"Set {key} to its absolute file path.",
                )
    seqs = {}
    try:
        seqs = genome(config["genome"])
        bases = sum(map(len, seqs.values()))
        if params["backend"] == "portable" and bases > 2_000_000:
            raise ValueError("Portable backend supports up to 2 million reference bases")
        check("Genome", "pass", f"{len(seqs)} sequences and {bases:,} reference bases")
        for key in ("reference", "repeats"):
            if config.get(key):
                intervals = bed(config[key], seqs)
                check(key.capitalize(), "pass", f"{len(intervals)} compatible BED regions")
        for kind, path in config.get("ncrna", {}).items():
            genome(path, rna=True)
            check(kind, "pass", "Filter FASTA readable")
    except (ValueError, OSError, EOFError, KeyError, TypeError) as exc:
        check(
            "Reference files",
            "error",
            str(exc),
            "Check the FASTA, BED coordinates and chromosome names.",
        )
    groups, ids, pairs = Counter(), set(), set()
    samples = config.get("samples", [])
    if not samples:
        check("Samples", "error", "At least one sample is required.", "Add a FASTQ file.")
    size = 0
    for sample in samples:
        name = str(sample.get("sample_id", ""))
        cond = str(sample.get("condition", "")).strip()
        rep = str(sample.get("replicate", "")).strip()
        if name == "cluster_id":
            check(
                "Sample ID",
                "error",
                "cluster_id is the matrix feature header.",
                "Choose a different sample ID.",
            )
        if not SAFE_ID.fullmatch(name) or name in ids or not cond or not rep or (cond, rep) in pairs:
            check(
                name or "Sample sheet",
                "error",
                "Missing or duplicate sample metadata.",
                "Use safe unique sample IDs, a condition and a unique replicate per condition.",
            )
        ids.add(name)
        groups[cond] += 1
        pairs.add((cond, rep))
        try:
            ad = adapter(sample)
            if is_paired(sample):
                if __package__:
                    from .paired import read_pairs, merge_pair
                else:
                    from paired import read_pairs, merge_pair
                sampled = list(islice(read_pairs(sample["fastq_path"], sample["fastq_r2_path"]), 1000))
                if not sampled:
                    raise ValueError("The paired FASTQ files are empty")
                merged = [insert for a, b in sampled if (insert := merge_pair(a, b)) is not None]
                size += sum(Path(sample[k]).stat().st_size for k in ("fastq_path", "fastq_r2_path"))
                check(f"{name} FASTQ pairs", "pass", f"Validated {len(sampled):,} sampled R1/R2 pairs with matching identifiers")
                check(f"{name} overlap", "pass" if len(merged) >= len(sampled)/2 else "warning",
                      f"{percentage(len(merged), len(sampled)):g}% of sampled pairs have a unique overlap of at least 12 nt.",
                      "Confirm R1/R2 orientation and library type. Unmerged pairs are discarded.")
                hist = Counter(map(len, merged))
                pct = percentage(sum(lo <= len(r) <= hi for r in merged), len(sampled))
                check(f"{name} lengths", "pass" if pct >= 20 else "warning",
                      f"{pct:g}% of sampled pairs yield an insert of {lo}–{hi} nt. "
                      + ("Length filtering is off; all nonempty merged inserts are retained for mapping." if params["length_filter"] == "all" else "Inserts outside the target range are excluded."),
                      "Review the library type and insert-length range." if pct < 20 else "")
                rows[-1]["histogram"] = dict(sorted(hist.items()))
                continue
            seq = list(islice(fastq(sample["fastq_path"]), 1000))
            if not seq:
                raise ValueError("FASTQ is empty")
            size += Path(sample["fastq_path"]).stat().st_size
            check(f"{name} FASTQ", "pass", f"Validated {len(seq):,} sampled records")
            try:
                positions = ([-1] * len(seq) if params["adapter_mode"] == "skip"
                             else adapter_positions(seq, ad, params["backend"]))
            except ImportError:
                check(f"{name} adapter", "error", "Cutadapt is unavailable for adapter pre-flight.",
                      "Relaunch the app to finish dependency installation.")
                continue
            hit = percentage(sum(p >= 0 for p in positions), len(seq))
            lengths = [p if p >= 0 else len(read) for p, read in zip(positions, seq)
                       if p >= 0 or params["adapter_mode"] != "require"]
            pct = percentage(sum(lo <= length <= hi for length in lengths), len(seq))
            check(
                f"{name} adapter",
                "pass" if hit >= 50 or params["adapter_mode"] == "skip" else "warning",
                ("Adapter trimming skipped: reads declared already trimmed." if params["adapter_mode"] == "skip" else f"{hit:g}% of sampled reads match the selected adapter ({ad}) using "
                + ("full exact matching." if params["backend"] == "portable" else "Cutadapt, including partial and error-tolerant matches.")),
                ("Unmatched reads are retained unchanged; this does not prove they were preprocessed. Confirm the library protocol." if params["adapter_mode"] == "retain" else "Unmatched reads are discarded in Require adapter mode. Choose Retain unmatched or Already trimmed for preprocessed data.") if hit < 50 and params["adapter_mode"] != "skip" else "",
            )
            if hit < 50 and params["adapter_mode"] != "skip":
                # Diagnostic evidence only: never silently change the user's adapter.
                candidates = []
                for kit, candidate in ADAPTERS.items():
                    if candidate == ad:
                        continue
                    full_hits = percentage(sum(candidate in read for read in seq), len(seq))
                    if full_hits >= 50:
                        candidates.append(f"{kit}: {full_hits:g}% full exact matches")
                if candidates:
                    rows[-1]["fix"] += " Other preset matches: " + "; ".join(candidates) + ". Confirm the kit before changing it."
            hist = Counter(lengths)
            check(
                f"{name} lengths",
                "pass" if pct >= 20 else "warning",
                f"{pct:g}% of sampled reads have a processed length of {lo}–{hi} nt. "
                + ("Length filtering is off; nonempty reads outside this range are retained for mapping." if params["length_filter"] == "all" else "Reads outside this range are excluded; widen the range or turn length filtering off to retain them."),
                ("Unmatched read lengths are sequenced lengths, not confirmed insert lengths." if hit < 50 and params["adapter_mode"] != "skip" else "Review the library type and insert-length range; read length alone does not establish that a read is piRNA.") if pct < 20 else "",
            )
            rows[-1]["histogram"] = dict(sorted(hist.items()))
        except (ValueError, OSError, EOFError, KeyError, TypeError) as exc:
            check(
                f"{name} input",
                "error",
                str(exc),
                "Provide a readable four-line FASTQ and valid adapter.",
            )
    for condition, count in groups.items():
        check(
            f"{condition} replicates",
            "pass" if count >= 2 else "warning",
            f"{count} replicate(s).",
            "You can continue with cluster discovery and descriptive fold changes. Add biological replicates for statistical differential-expression testing." if count < 2 else "",
        )
    disk = max(2_000_000, size * 15)
    available = shutil.disk_usage(Path.cwd()).free
    check(
        "Resources",
        "warning" if disk > available else "pass",
        f"Estimated disk {disk / 1e6:.1f} MB, memory {max(32, (size * 15 + sum(map(len, seqs.values())) * 4) / 1e6):.0f} MB. Estimates depend on mapping multiplicity.",
        "Check available disk before running." if disk > available else "",
    )
    return rows
