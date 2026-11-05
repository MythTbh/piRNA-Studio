"""Deterministic synthetic reads from two artificial contigs; no organism-specific claims."""

import csv
import gzip
import json
import random
from pathlib import Path

out = Path(__file__).resolve().parent
rng = random.Random(441)


def dna(n):
    return "".join(rng.choices("ACGT", k=n))


def rc(s):
    return s.translate(str.maketrans("ACGT", "TGCA"))[::-1]


genome = {c: list(dna(25000)) for c in ["syn2L", "syn2R"]}
loci = []
for chrom, seq in genome.items():
    for k in range(9):
        left = 650 + k * 2600
        starts = []
        for j in range(29):
            pos = left + j * 41
            size = rng.choices(range(24, 33), weights=[2, 4, 8, 13, 8, 6, 4, 2, 1])[0]
            seq[pos] = "T"
            if j % 2 == 0:
                seq[pos + 9] = "A"
            starts.append((pos, size, "+"))
            if k % 4 != 3:
                starts.append((pos + 10 - size, size, "-"))
        loci.append((chrom, left, starts))
genome = {k: "".join(v) for k, v in genome.items()}
(out / "genome.fa").write_text("".join(f">{c}\n{s}\n" for c, s in genome.items()))
(out / "reference.bed").write_text(
    "".join(
        f"{c}\t{start - 8}\t{start + 1185}\tREF-{i + 1:02}\n"
        for i, (c, start, _) in enumerate(loci)
        if i != 15
    )
    + "syn2L\t23500\t24800\tREF-19\n"
)
nc = dna(29)
(out / "rRNA.fa").write_text(f">synthetic-rRNA\n{nc}\n")
samples = []
for cond in ["Control", "Perturbed"]:
    for rep in range(1, 4):
        sid = f"{cond.lower()}_{rep}"
        reads = []
        for i, (chrom, left, starts) in enumerate(loci):
            depth = (
                (10 if i % 5 == 0 else 1 if i % 5 == 1 else 3)
                if cond == "Perturbed"
                else (1 if i % 5 == 0 else 10 if i % 5 == 1 else 3)
            )
            for pos, size, strand in starts:
                seq = genome[chrom][pos : pos + size]
                if strand == "-":
                    seq = rc(seq)
                reads.extend([seq] * (max(1, depth + rng.randint(-1, 1))))
        reads += (
            ["A" * 26] * 35
            + [nc] * 50
            + [dna(rng.choice([16, 18, 19, 20, 21, 22, 23, 33, 34, 36])) for _ in range(670)]
        )
        ad = "TGGAATTCTCGGGTGCCAAGG"
        reads = [r + ad for r in reads] + [dna(49) for _ in range(270)]
        rng.shuffle(reads)
        data = "".join(f"@r{i}\n{seq}\n+\n{'I' * len(seq)}\n" for i, seq in enumerate(reads))
        (out / f"{sid}.fastq.gz").write_bytes(gzip.compress(data.encode(), mtime=0))
        samples.append(
            dict(
                sample_id=sid,
                condition=cond,
                replicate=rep,
                fastq_path=f"{sid}.fastq.gz",
                library_kit="TruSeq",
            )
        )
with (out / "samples.csv").open("w", newline="") as stream:
    w = csv.DictWriter(stream, fieldnames=list(samples[0]))
    w.writeheader()
    w.writerows(samples)
(out / "config.json").write_text(
    json.dumps(
        dict(
            genome="genome.fa",
            reference="reference.bed",
            ncrna={"rRNA": "rRNA.fa"},
            samples=samples,
            params={"de_method": "auto"},
            dataset="Synthetic two-condition benchmark",
        ),
        indent=2,
    )
    + "\n"
)
