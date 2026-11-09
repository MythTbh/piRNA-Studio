"""Adapters for locally installed research tools. No shell or downloaded Perl code."""

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__:
    from .science import Hit
    from . import batches
else:
    from science import Hit
    import batches


def invoke(command, folder):
    with (folder / "commands.log").open("a") as stream:
        print(repr(command), file=stream, flush=True)
        subprocess.run(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT, check=True)


def trim(path, adapter, folder, mode="require"):
    # Use exact full adapters in the portable path; cutadapt uses its default error tolerance.
    if mode == "skip":
        return Path(path)
    output = folder / "trimmed.fastq"
    context = json.dumps([batches.digest(path), adapter, mode,
                          subprocess.check_output(["cutadapt", "--version"], text=True).strip()])
    outputs = ["trimmed.fastq", "trim-summary.json"]
    checkpoint = folder / "trim-cache"
    checkpoint.mkdir(exist_ok=True)
    # Reuse only complete outputs with matching content and tool version.
    try:
        saved = json.loads((checkpoint / "complete.json").read_text())
        if saved["key"] == context and all(saved["outputs"][n] == batches.digest(folder / n) for n in outputs):
            return output
    except (OSError, ValueError, KeyError):
        pass
    (checkpoint / "complete.json").unlink(missing_ok=True)
    invoke(
        [
            "cutadapt", "-j", "2", "--json", str(folder / "trim-summary.json"),
            "-a",
            adapter,
            *(["--discard-untrimmed"] if mode == "require" else []),
            "-o",
            str(output),
            str(Path(path).resolve()),
        ],
        folder,
    )
    record = {"key": context, "outputs": {n: batches.digest(folder / n) for n in outputs}}
    temporary = checkpoint / "complete.tmp"
    temporary.write_text(json.dumps(record))
    temporary.replace(checkpoint / "complete.json")
    return output


def write_collapsed(path, counts):
    with path.open("w") as stream:
        for seq, n in sorted(counts.items()):
            stream.write(f">{n}\n{seq}\n")


def dust(counts, folder):
    if not counts:
        return {}
    return batches.dust(counts, folder, invoke)


def align(seqs, genome, folder):
    mapfile = folder / "aligned.map"
    if not seqs:
        mapfile.write_bytes(b"")
        return []
    batches.map_reads(seqs, genome, folder, invoke)
    multiplicity = Counter()
    with mapfile.open() as stream:
        for line in stream:
            if line.strip():
                multiplicity[line.split()[4].upper()] += 1
    hits = []
    with mapfile.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            chrom, pos, ref, header, seq, mm, strand = line.rstrip().split()[:7]
            seq = seq.upper()
            start = int(pos) - 1
            hits.append(Hit(chrom, start, start + len(ref), strand, seq, seqs[seq], multiplicity[seq]))
    return hits


def call(genome, folder, params):
    mapfile = folder / "aligned.map"
    if not mapfile.stat().st_size:
        return []
    with TemporaryDirectory(prefix="protrac-", dir=folder) as tmp:
        native = Path(tmp)
        # Hard links do not require Windows Developer Mode or administrator rights.
        # Fall back to a copy on filesystems without hard-link support.
        try:
            os.link(mapfile.resolve(), native / mapfile.name)
        except OSError:
            shutil.copyfile(mapfile, native / mapfile.name)
        profile_args = (
            ["-1Tor10A", "0.5", "-1Tand10A", "0.3", "-clstrand", "0.5", "-pdens", "0.05"]
            if params["protrac_profile"] == "clusterdb"
            else []
        )
        try:
            invoke(
                [
                    "perl",
                    os.environ["PROTRAC_PL"],
                    "-map",
                    mapfile.name,
                    "-genome",
                    str(genome),
                    "-format",
                    "ELAND3",
                    "-clsize",
                    str(params["min_cluster_size"]),
                    "-pimin",
                    str(params["min_length"]),
                    "-pimax",
                    str(params["max_length"]),
                    "-nohtml",
                    "-nomotif",
                    *profile_args,
                ],
                native,
            )
        finally:
            if (native / "commands.log").is_file():
                with (folder / "commands.log").open("a") as log:
                    log.write((native / "commands.log").read_text())
        tables = list(native.rglob("results.table"))
        if len(tables) != 1:
            raise RuntimeError("proTRAC produced no single results.table. Inspect commands.log.")
        shutil.copy(tables[0], folder / "results.table")
        return parse_calls(tables[0].read_text())


def parse_calls(table):
    calls = [
        (chrom, int(a) - 1, int(b))
        for chrom, a, b in re.findall(
            r"^Cluster \d+\tLocation: ([^\t]+)\tCoordinates: (\d+)-(\d+)", table, re.MULTILINE
        )
    ]
    summary = re.search(r"Total size of (\d*) predicted piRNA clusters", table)
    if not summary or int(summary[1] or "0") != len(calls):
        raise RuntimeError("Unexpected proTRAC summary or coordinates. Inspect its results.table.")
    return sorted(calls)
