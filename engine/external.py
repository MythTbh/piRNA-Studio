"""Adapters for locally installed research tools. No shell or downloaded Perl code."""

import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__:
    from .science import Hit
else:
    from science import Hit


def invoke(command, folder):
    with (folder / "commands.log").open("a") as stream:
        print(repr(command), file=stream, flush=True)
        subprocess.run(command, cwd=folder, stdout=stream, stderr=subprocess.STDOUT, check=True)


def trim(path, adapter, folder, mode="require"):
    # Use exact full adapters in the portable path; cutadapt uses its default error tolerance.
    if mode == "skip":
        return Path(path)
    output = folder / "trimmed.fastq"
    invoke(
        [
            "cutadapt",
            "-a",
            adapter,
            *(["--discard-untrimmed"] if mode == "require" else []),
            "-o",
            str(output),
            str(Path(path).resolve()),
        ],
        folder,
    )
    return output


def write_collapsed(path, counts):
    with path.open("w") as stream:
        for seq, n in sorted(counts.items()):
            stream.write(f">{n}\n{seq}\n")


def dust(counts, folder):
    if not counts:
        return {}
    src = folder / "collapsed.fa"
    write_collapsed(src, counts)
    invoke(["perl", os.environ["DUSTER_PL"], "-i", src.name], folder)
    out = {}
    with (folder / (src.name + ".no-dust")).open() as stream:
        for head in stream:
            if not head.startswith(">"):
                raise ValueError("Unexpected duster FASTA output")
            out[next(stream).strip().upper()] = int(head[1:].strip())
    return out


def align(seqs, genome, folder):
    if not seqs:
        (folder / "aligned.map").write_bytes(b"")
        return []
    src = folder / "filtered.fa"
    write_collapsed(src, seqs)
    mapfile = folder / "aligned.map"
    invoke(
        [
            "perl",
            os.environ["SRNAMAPPER_PL"],
            "-input",
            src.name,
            "-genome",
            str(genome),
            "-alignments",
            "best",
            "-format",
            "eland",
            "-output",
            mapfile.name,
        ],
        folder,
    )
    raw = []
    multiplicity = Counter()
    with mapfile.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            chrom, pos, ref, header, seq, mm, strand = line.rstrip().split()[:7]
            start = int(pos) - 1
            seq = seq.upper()
            if seq not in seqs:
                raise ValueError("Mapper returned a sequence absent from the filtered FASTA")
            if strand not in {"+", "-"} or start < 0:
                raise ValueError("Invalid ELAND alignment")
            raw.append((chrom, start, start + len(ref), strand, seq))
            multiplicity[seq] += 1
    hits = [Hit(*r, seqs[r[-1]], multiplicity[r[-1]]) for r in raw]
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
