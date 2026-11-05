"""Durable run lifecycle and searchable scientific output indexes."""

import json
import platform
from importlib import metadata
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "failed", "cancelled"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        # Only the process owning this directory may recover interrupted jobs.
        self.owner_lock = (self.directory / ".server.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.owner_lock.seek(0)
                msvcrt.locking(self.owner_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner_lock.close()
            raise RuntimeError(
                "Another piRNA Studio server already uses this data directory"
            ) from None
        self.db = self.directory / "studio.sqlite3"
        self.lock = threading.RLock()
        self.workers = {}
        self.compute_slot = threading.Semaphore(1)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(
                  run_id TEXT PRIMARY KEY, created_at TEXT, status TEXT, stage TEXT,
                  progress REAL, error TEXT, params_json TEXT, genome_name TEXT, genome_checksum TEXT);
                CREATE TABLE IF NOT EXISTS logs(run_id TEXT, message TEXT);
                CREATE INDEX IF NOT EXISTS log_runs ON logs(run_id);
                CREATE TABLE IF NOT EXISTS clusters(run_id TEXT,cluster_id TEXT,chr TEXT,start INTEGER,
                  end INTEGER,length INTEGER,strand_mode TEXT,support_n INTEGER,total_reads REAL,repeat_pct REAL,
                  payload TEXT,PRIMARY KEY(run_id,cluster_id));
                CREATE TABLE IF NOT EXISTS cluster_counts(run_id TEXT,cluster_id TEXT,sample_id TEXT,count REAL);
                CREATE TABLE IF NOT EXISTS samples(run_id TEXT,sample_id TEXT,condition TEXT,replicate TEXT,kit TEXT,
                  fastq_checksum TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS qc(run_id TEXT,sample_id TEXT,total_reads INTEGER,piRNA_range_pct REAL,
                  unique_pct REAL,u1_pct REAL,a10_pct REAL,pingpong_z REAL,status TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS read_accounting(run_id TEXT,sample_id TEXT,stage TEXT,reads REAL);
                CREATE TABLE IF NOT EXISTS de_results(run_id TEXT,contrast TEXT,cluster_id TEXT,base_mean REAL,log2fc REAL,
                  pvalue REAL,padj REAL,flag TEXT,payload TEXT);
                CREATE TABLE IF NOT EXISTS validation_clusters(run_id TEXT,cluster_id TEXT,status TEXT,ref_id TEXT);
                CREATE TABLE IF NOT EXISTS validation(run_id TEXT,metric TEXT,value TEXT);
                CREATE TABLE IF NOT EXISTS provenance(run_id TEXT,key TEXT,value TEXT);
            """)
            db.execute("""UPDATE runs SET status='failed',stage='Interrupted',error='Server stopped during processing. Submit the inputs again.'
                          WHERE status IN ('running','queued')""")

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.db, timeout=15)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def list_runs(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT run_id, created_at,status,stage,progress,genome_name FROM runs ORDER BY created_at DESC, rowid DESC"
                )
            ]

    def status(self, run_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT run_id,created_at,status,stage,progress,error FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown run")
            status = dict(row)
            status["logs"] = [
                r[0]
                for r in db.execute(
                    "SELECT message FROM (SELECT rowid,message FROM logs WHERE run_id=? ORDER BY rowid DESC LIMIT 250) ORDER BY rowid",
                    (run_id,),
                )
            ]
            status["accounting"] = []
            if status["status"] == "completed":
                status["accounting"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT sample_id,stage,reads FROM read_accounting WHERE run_id=? ORDER BY rowid",
                        (run_id,),
                    )
                ]
            elif status["status"] == "running":
                partial = (
                    self.directory / run_id / "outputs" / "read-accounting.partial.json"
                )
                try:
                    status["accounting"] = json.loads(partial.read_text())
                except (FileNotFoundError, ValueError):
                    pass
            return status

    def submit(self, staged, config):
        run_id = uuid.uuid4().hex
        config = {**config, "run_id": run_id}
        dest = self.directory / run_id
        staged.rename(dest)
        # Input paths in config are relative to the per-run working directory.
        (dest / "config.json").write_text(json.dumps(config, indent=2))
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    utc_now(),
                    "queued",
                    "Queued",
                    0,
                    None,
                    json.dumps(config.get("params", {})),
                    Path(config["genome"]).name,
                    None,
                ),
            )
        threading.Thread(target=self._await_slot, args=(run_id,), daemon=True).start()
        return run_id

    def cancel(self, run_id):
        with self.lock, self.connect() as db:
            status = self.status(run_id)
            if status["status"] in TERMINAL:
                return status
            db.execute(
                "UPDATE runs SET status='cancelled',stage='Cancelled' WHERE run_id=?",
                (run_id,),
            )
            db.execute(
                "INSERT INTO logs VALUES(?,?)", (run_id, "Cancellation requested.")
            )
            process = self.workers.get(run_id)
            if process and process.poll() is None:
                try:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            db.commit()
            return self.status(run_id)

    def _await_slot(self, run_id):
        with self.compute_slot:
            self._execute(run_id)

    def _execute(self, run_id):
        run_dir = self.directory / run_id
        try:
            with self.lock, self.connect() as db:
                if self.status(run_id)["status"] == "cancelled":
                    return
                db.execute(
                    "UPDATE runs SET status='running',stage='Starting' WHERE run_id=?",
                    (run_id,),
                )
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        str(ROOT / "engine" / "pipeline.py"),
                        "config.json",
                        "outputs",
                    ],
                    cwd=run_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    start_new_session=True,
                )
                self.workers[run_id] = process
            last_line = ""
            with process.stdout as console:
                for line in console:
                    last_line = line.strip()[-2000:]
                    if not last_line:
                        continue
                    update = {}
                    try:
                        parsed = json.loads(last_line)
                        if isinstance(parsed, dict):
                            update = parsed
                    except ValueError:
                        pass
                    with self.connect() as db:
                        db.execute(
                            "INSERT INTO logs VALUES(?,?)",
                            (run_id, str(update.get("message", last_line))),
                        )
                        if "stage" in update and isinstance(
                            update.get("percent"), (float, int)
                        ):
                            db.execute(
                                "UPDATE runs SET stage=?,progress=? WHERE run_id=? AND status='running'",
                                (
                                    str(update["stage"]),
                                    min(99, max(0, update["percent"])),
                                    run_id,
                                ),
                            )
            return_code = process.wait()
            with self.lock, self.connect() as db:
                if self.status(run_id)["status"] == "cancelled":
                    return
                if return_code:
                    raise RuntimeError(
                        last_line or f"Analysis exited with code {return_code}"
                    )
                result = json.loads((run_dir / "outputs" / "results.json").read_text())
                environment = {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "tools": result["provenance"]["tools"],
                    "packages": {
                        d.metadata["Name"]: d.version
                        for d in metadata.distributions()
                        if d.metadata["Name"]
                    },
                }
                (run_dir / "outputs" / "environment-lock.json").write_text(
                    json.dumps(environment, indent=2, sort_keys=True)
                )
                self._index(db, run_id, result)
                db.execute(
                    "UPDATE runs SET status='completed',stage='Complete',progress=100 WHERE run_id=?",
                    (run_id,),
                )
        except Exception as exc:
            with self.connect() as db:
                db.execute(
                    "UPDATE runs SET status='failed',stage='Failed',error=? WHERE run_id=? AND status!='cancelled'",
                    (str(exc), run_id),
                )
        finally:
            with self.lock:
                self.workers.pop(run_id, None)

    def _index(self, db, rid, result):
        dump = json.dumps
        config = json.loads((self.directory / rid / "config.json").read_text())
        checksums = {r["name"]: r["sha256"] for r in result["provenance"]["inputs"]}
        fastq_by_id = {
            s["sample_id"]: Path(s["fastq_path"]).name for s in config["samples"]
        }
        db.execute(
            "UPDATE runs SET genome_checksum=? WHERE run_id=?",
            (checksums.get(Path(config["genome"]).name), rid),
        )
        for sample in result["samples"]:
            db.execute(
                "INSERT INTO samples VALUES(?,?,?,?,?,?,?)",
                (
                    rid,
                    sample["sample_id"],
                    sample.get("condition"),
                    sample.get("replicate"),
                    sample.get("library_kit"),
                    checksums.get(fastq_by_id[sample["sample_id"]]),
                    dump(sample),
                ),
            )
        for q in result["qc"]:
            fields = (
                "sample_id",
                "total_reads",
                "piRNA_range_pct",
                "unique_pct",
                "u1_pct",
                "a10_pct",
                "pingpong_z",
                "status",
            )
            db.execute(
                "INSERT INTO qc VALUES(?,?,?,?,?,?,?,?,?,?)",
                (rid, *(q.get(k) for k in fields), dump(q)),
            )
        for a in result["accounting"]:
            db.execute(
                "INSERT INTO read_accounting VALUES(?,?,?,?)",
                (rid, a["sample_id"], a["stage"], a["reads"]),
            )
        for c in result["clusters"]:
            db.execute(
                "INSERT INTO clusters VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    c["cluster_id"],
                    c["chr"],
                    c["start"],
                    c["end"],
                    c["length"],
                    c["strand_mode"],
                    c["support_n"],
                    c["total_reads"],
                    c.get("repeat_pct"),
                    dump(c),
                ),
            )
            db.executemany(
                "INSERT INTO cluster_counts VALUES(?,?,?,?)",
                [(rid, c["cluster_id"], s, x) for s, x in c["counts"].items()],
            )
        for d in result["de"]:
            fields = (
                "contrast",
                "cluster_id",
                "base_mean",
                "log2fc",
                "pvalue",
                "padj",
                "flag",
            )
            db.execute(
                "INSERT INTO de_results VALUES(?,?,?,?,?,?,?,?,?)",
                (rid, *(d.get(k) for k in fields), dump(d)),
            )
        validation = result["validation"]
        for record in validation.get("matched", []):
            db.execute(
                "INSERT INTO validation_clusters VALUES(?,?,?,?)",
                (rid, record["cluster_id"], "matched", record["ref_id"]),
            )
        for ref_id in validation.get("missed", []):
            db.execute(
                "INSERT INTO validation_clusters VALUES(?,?,?,?)",
                (rid, None, "missed", ref_id),
            )
        for cid in validation.get("extra", []):
            db.execute(
                "INSERT INTO validation_clusters VALUES(?,?,?,?)",
                (rid, cid, "extra", None),
            )
        for key, table in [("validation", "validation"), ("provenance", "provenance")]:
            db.executemany(
                f"INSERT INTO {table} VALUES(?,?,?)",
                [(rid, k, dump(v)) for k, v in result[key].items()],
            )

    def cluster_page(self, rid, query):
        clauses, args = ["run_id=?"], [rid]
        for key in ("chr", "strand_mode"):
            if query.get(key):
                clauses.append(key + "=?")
                args.append(query[key])
        for key, field in [
            ("min_reads", "total_reads"),
            ("min_length", "length"),
            ("min_support", "support_n"),
        ]:
            if key in query:
                clauses.append(field + ">=?")
                args.append(int(query[key]))
        if query.get("search"):
            clauses.append("instr(lower(cluster_id||' '||chr),lower(?))>0")
            args.append(query["search"])
        where = " AND ".join(clauses)
        field = query.get("sort", "cluster_id")
        if field not in (
            "cluster_id",
            "chr",
            "start",
            "end",
            "length",
            "total_reads",
            "support_n",
            "strand_mode",
        ):
            raise ValueError("Unknown sort field")
        order = "DESC" if query.get("order") == "desc" else "ASC"
        limit = max(1, min(1000, int(query.get("limit", 100))))
        offset = max(0, int(query.get("offset", 0)))
        with self.connect() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM clusters WHERE " + where, args
            ).fetchone()[0]
            rows = db.execute(
                f"SELECT payload FROM clusters WHERE {where} ORDER BY {field} {order},cluster_id LIMIT ? OFFSET ?",
                args + [limit, offset],
            )
            return {
                "clusters": [json.loads(row[0]) for row in rows],
                "total": count,
                "limit": limit,
                "offset": offset,
            }
