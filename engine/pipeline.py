#!/usr/bin/env python3
"""Run piRNA Studio with a JSON sample configuration and an output directory."""

import argparse
import csv
import json
import os
import platform
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory

if __package__:
    from . import inputs, science, external
    from .differential import differential
    from .report import report
else:
    import inputs
    import science
    import external
    from differential import differential
    from report import report

preflight = inputs.preflight
pct = inputs.percentage


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def trim_collapse(sample, params, folder):
    ad = inputs.adapter(sample)
    source = sample["fastq_path"]
    lo, hi = params["min_length"], params["max_length"]
    mode = params.get("adapter_mode", "retain")
    def keep(length):
        return length > 0 and (params.get("length_filter", "range") == "all" or lo <= length <= hi)
    portable = params["backend"] == "portable"
    hist = Counter()
    collapsed = Counter()
    total = 0
    if inputs.is_paired(sample):
        if __package__:
            from .paired import read_pairs, merge_pair
        else:
            from paired import read_pairs, merge_pair
        for r1, r2 in read_pairs(source, sample["fastq_r2_path"]):
            total += 1
            insert = merge_pair(r1, r2)
            if insert is not None:
                hist[len(insert)] += 1
                if keep(len(insert)):
                    collapsed[insert] += 1
    elif portable or mode == "skip":
        for raw in inputs.fastq(source):
            total += 1
            index = raw.find(ad) if mode != "skip" else -1
            if index < 0 and mode != "require":
                index = len(raw)
            if index >= 0:
                hist[index] += 1
                if keep(index):
                    collapsed[raw[:index]] += 1
    else:
        total = sum(1 for _ in inputs.fastq(source))
        trimmed = external.trim(source, ad, folder, mode)
        # cutadapt can emit zero-length inserts; a FASTQ parser accepting blank sequences is needed here.
        with trimmed.open() as stream:
            for _ in stream:
                seq = next(stream).strip()
                next(stream)
                next(stream)
                hist[len(seq)] += 1
                if keep(len(seq)):
                    collapsed[seq] += 1
    return total, hist, collapsed


def complexity(collapsed, params, folder):
    if params["backend"] == "portable":
        external.write_collapsed(folder / "collapsed.fa", collapsed)
        return {s: n for s, n in collapsed.items() if science.complex_enough(s)}
    return external.dust(collapsed, folder)


def ncrna_filter(keep, filter_refs):
    stages = []
    for kind, refs in filter_refs.items():
        keep = {s: n for s, n in keep.items() if next(science.loci(s, refs), None) is None}
        stages.append((f"After {kind}", sum(keep.values())))
    return keep, stages


def qc_profile(sid, total, hist, collapsed, hits, params):
    lo, hi = params["min_length"], params["max_length"]
    in_range = {seq: count for seq, count in collapsed.items() if lo <= len(seq) <= hi}
    sized = sum(in_range.values())
    mapped = sum({h.seq: h.reads for h in hits}.values())
    overlap, z, partners = science.pingpong(hits, lo)
    peak = max(hist, key=hist.get) if hist else None
    sized_pct = pct(sized, total)
    unique_pct = pct(len(in_range), sized)
    u1 = pct(sum(h.weight for h in hits if h.seq[0] == "T"), mapped)
    a10 = pct(sum(h.weight for h in hits if len(h.seq) >= 10 and h.seq[9] == "A"), mapped)
    checks = {
        "length": sized_pct >= 20 and peak is not None and lo <= peak <= hi,
        "diversity": unique_pct >= 10,
        "bias": max(u1, a10) >= 35,
        "pingpong": z is not None and z > 1.65,
    }
    qc = dict(
        sample_id=sid,
        total_reads=total,
        piRNA_range_pct=sized_pct,
        unique_pct=unique_pct,
        u1_pct=u1,
        a10_pct=a10,
        pingpong_z=z,
        status="pass" if all(checks.values()) else "warning",
        checks=checks,
        length_histogram=dict(sorted(hist.items())),
        overlap_histogram=overlap,
        peak_length=peak,
        mapped_reads=mapped,
    )
    return qc, partners


def profile(sample, seqs, filter_refs, params, folder, genome_path):
    total, hist, collapsed = trim_collapse(sample, params, folder)
    keep = complexity(collapsed, params, folder)
    stages = [
        ("Input", total),
        ("Pairs merged" if inputs.is_paired(sample) else "Adapter processed", sum(hist.values())),
        ("Length filter off" if params.get("length_filter") == "all" else "Length filtered", sum(collapsed.values())),
        ("Complexity filtered", sum(keep.values())),
    ]
    keep, nc_stages = ncrna_filter(keep, filter_refs)
    stages.extend(nc_stages)
    if params["backend"] == "portable":
        hits = science.portable_align(keep, seqs)
        calls = science.portable_calls(hits, params)
    else:
        hits = external.align(keep, genome_path, folder)
        calls = external.call(genome_path, folder, params)
    metrics, partners = qc_profile(sample["sample_id"], total, hist, collapsed, hits, params)
    stages.append(("Genome mapped", metrics["mapped_reads"]))
    return hits, calls, metrics, stages, partners


def table(path, fields, rows):
    with path.open("w", newline="", encoding="utf8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, delimiter="\t", extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run(config, outdir, progress=None, prepared=None):
    out = Path(outdir).resolve()
    out.mkdir(exist_ok=True, parents=True)
    if prepared is None and (out / "results.json").exists():
        raise FileExistsError(
            "This directory contains a completed analysis. Choose a fresh output directory."
        )
    emit = progress or (lambda *args: None)
    start = timestamp()
    params = {**inputs.DEFAULTS, **config.get("params", {})}
    emit("Preflight", 0, "Checking input files and parameters")
    checks = preflight(config, check_tools=prepared is None)
    bad = [c["message"] for c in checks if c["severity"] == "error"]
    if bad:
        raise ValueError("Preflight failed: " + "; ".join(bad))
    seqs = inputs.genome(config["genome"])
    samples = config["samples"]
    refs = {k: inputs.genome(v, rna=True) for k, v in config.get("ncrna", {}).items()}
    qc, accounting = [], []
    all_hits, calls, partners = {}, {}, {}
    with TemporaryDirectory(dir=out) as tmp:
        folder = Path(tmp)
        genome_path = folder / "genome.fa"
        if params["backend"] == "protrac" and prepared is None:
            # Use first-word contig IDs and unpack compressed FASTA for the Perl tools.
            inputs.write_genome(genome_path, seqs)
        for index, sample in enumerate(samples):
            sid = sample["sample_id"]
            emit("Mapping and cluster calling", 5 + int(65 * index / len(samples)), f"Processing {sid}")
            directory = folder / "samples" / sid
            directory.mkdir(parents=True)
            try:
                if prepared is None:
                    hits, found, metrics, stages, paired = profile(
                        sample, seqs, refs, params, directory, genome_path
                    )
                else:
                    record = json.loads(Path(prepared[sid]).read_text())
                    hits = [science.Hit(*row) for row in record["hits"]]
                    found, metrics, stages, paired = (
                        record[key] for key in ("calls", "qc", "accounting", "partners")
                    )
            finally:
                import shutil

                # Preserve tool commands, native output and collapsed reads for inspection.
                archive = out / "intermediate" / sid
                archive.mkdir(exist_ok=True, parents=True)
                for path in directory.rglob("*"):
                    if path.is_file() and (
                        path.name
                        in {
                            "commands.log",
                            "results.table",
                            "filtered.fa",
                            "collapsed.fa",
                            "aligned.map",
                        }
                        or path.suffix == ".gtf"
                    ):
                        shutil.copy(path, archive / path.name)
            all_hits[sid], calls[sid], partners[sid] = hits, found, paired
            qc.append(metrics)
            accounting.extend(dict(sample_id=sid, stage=name, reads=n) for name, n in stages)
            dump(out / "read-accounting.partial.tmp", accounting)
            (out / "read-accounting.partial.tmp").replace(out / "read-accounting.partial.json")
    emit("Consensus and counting", 72, "Combining replicate-supported calls and assigning reads")
    intervals = science.consensus(calls, samples, params["support"])
    repeats = inputs.bed(config["repeats"], seqs) if config.get("repeats") else []
    clusters, integers = science.counts_and_clusters(intervals, all_hits, calls, params, repeats)
    coverage = Counter()
    for sid, hits in all_hits.items():
        accounting.append(
            dict(sample_id=sid, stage="In clusters", reads=sum(c["counts"][sid] for c in clusters))
        )
        for h in hits:
            if params["count_mode"] != "unique" or h.multiplicity == 1:
                coverage[(h.chrom, h.start, h.end, h.strand)] += h.weight
    tracks = [
        dict(chr=c, start=a, end=b, strand=s, count=n) for (c, a, b, s), n in sorted(coverage.items())
    ]
    emit("Differential expression", 82, "Evaluating integer unique-read counts")
    de, method = differential(integers, samples, params)
    emit("Validation and report", 92, "Comparing BED intervals and writing outputs")
    validation = science.validate(
        clusters, inputs.bed(config["reference"], seqs) if config.get("reference") else None
    )
    tools = {"Python": platform.python_version(), "piRNA Studio engine": "1.0"}
    if prepared is not None:
        tools["Snakemake"] = os.environ.get("PIRNA_SNAKEMAKE_VERSION", "unknown")
    if method.startswith("PyDESeq2"):
        tools["PyDESeq2"] = metadata.version("pydeseq2")
    if params["backend"] == "protrac":
        from subprocess import check_output

        if prepared is None:
            tools["cutadapt"] = check_output(["cutadapt", "--version"], text=True).strip()
        else:
            tools["cutadapt"] = record["cutadapt_version"]
        tools["Perl"] = check_output(["perl", "-e", "print $^V"], text=True).strip()
        for key in ("DUSTER_PL", "SRNAMAPPER_PL", "PROTRAC_PL"):
            script = Path(os.environ[key])
            version = re.search(
                r'(?:\$proTRAC_version\s*=\s*"|Version[: ]+\s*[. ]*)(\d+(?:\.\d+)+)',
                script.read_text(errors="replace"),
                re.I,
            )
            tools[key] = f"{version[1] if version else script.name} (sha256 {inputs.checksum(script)})"
        mapping = "For single-end libraries, cutadapt trimmed adapters. For all libraries, duster filtered low-complexity reads, sRNAmapper produced best ELAND alignments, and proTRAC called sample clusters."
        if params["protrac_profile"] == "clusterdb":
            mapping += " The clusterdb caller profile used -1Tor10A 0.5, -1Tand10A 0.3, -clstrand 0.5 and -pdens 0.05."
    else:
        mapping = f"For single-end libraries, full exact adapter matches were trimmed. Shannon entropy ≥1.2 retained complex reads. The small-reference backend mapped exact matches on both strands and joined at least {params['min_loci']} loci separated by at most {params['max_gap']} bp."
    mapping += " In retain mode unmatched reads were kept unchanged; skip mode bypassed adapter trimming; require mode discarded unmatched reads."
    methods = (
        f"{mapping} Adapter mode: {params['adapter_mode']}; length filter: {params['length_filter']}. "
        f"The target RNA length window was {params['min_length']}–{params['max_length']} nt; with length filtering off, all nonempty processed reads were retained for mapping. Sample calls required {params['min_cluster_size']} bp. "
        f"Consensus required overlap in {params['support']} replicates per condition (all if fewer). "
        f"Counts used {params['count_mode']} assignment by 5′ end. {method}"
    )
    if any(inputs.is_paired(sample) for sample in samples):
        methods += (" Paired-end libraries used piRNA Studio overlap assembly in R1 orientation, with "
                    "at least 12 overlapping bases and at most 10% mismatches. Unique best overlaps "
                    "remove read-through adapters. Higher-quality bases resolve disagreements; equal-quality "
                    "disagreements become N. Unmerged pairs were discarded. Each assembled pair counted once. "
                    "Input and retained-read metrics for paired libraries are molecule/pair counts.")
        tools["piRNA Studio pair assembler"] = "1.0"
    paths = (
        [config["genome"]]
        + [s[k] for s in samples for k in ("fastq_path", "fastq_r2_path") if s.get(k)]
        + list(config.get("ncrna", {}).values())
        + [config[k] for k in ("reference", "repeats") if config.get(k)]
    )
    checksums = {p: inputs.checksum(p) for p in dict.fromkeys(paths)}
    manifest = [
        dict(name=Path(p).name, sha256=checksums[p], bytes=Path(p).stat().st_size) for p in paths
    ]
    prov = dict(
        created_at=start,
        completed_at=timestamp(),
        run_id=config.get("run_id", str(uuid.uuid4())),
        dataset=config.get("dataset", "Uploaded samples"),
        genome=Path(config["genome"]).name,
        reference_assembly=config.get("reference_assembly"),
        chromosome_lengths={c: len(seq) for c, seq in seqs.items()},
        parameters=params,
        tools=tools,
        inputs=manifest,
        methods=methods,
        de_method=method,
        coordinate_system="0-based half-open (BED); GFF3 is 1-based inclusive",
    )
    public = []
    for sample in samples:
        item = {k: v for k, v in sample.items() if k not in {"fastq_path", "fastq_r2_path"}}
        item.update(
            fastq_name=Path(sample["fastq_path"]).name,
            fastq_checksum=checksums[sample["fastq_path"]],
            adapter=inputs.adapter(sample),
        )
        item["layout"] = "paired" if inputs.is_paired(sample) else "single"
        if inputs.is_paired(sample):
            item.update(fastq_r2_name=Path(sample["fastq_r2_path"]).name,
                        fastq_r2_checksum=checksums[sample["fastq_r2_path"]])
        public.append(item)
    dump(
        out / "environment-lock.json",
        dict(
            python=platform.python_version(),
            platform=platform.platform(),
            tools=tools,
            packages={
                d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata["Name"]
            },
        ),
    )

    result = dict(
        samples=public,
        qc=qc,
        accounting=accounting,
        clusters=clusters,
        tracks=tracks,
        de=de,
        validation=validation,
        provenance=prov,
    )
    for filename, data in [
        ("qc", qc),
        ("validation", validation),
        ("provenance", prov),
        ("preflight", checks),
        ("pingpong-partners", partners),
    ]:
        dump(out / (filename + ".json"), data)
    ids = [s["sample_id"] for s in samples]
    table(
        out / "counts.tsv",
        ["cluster_id"] + ids,
        [dict(cluster_id=c["cluster_id"], **c["counts"]) for c in clusters],
    )
    table(
        out / "de-counts.tsv",
        ["cluster_id"] + ids,
        [dict(cluster_id=cid, **row) for cid, row in integers.items()],
    )
    table(out / "read-accounting.tsv", ["sample_id", "stage", "reads"], accounting)
    table(
        out / "clusters.tsv",
        [
            "cluster_id",
            "chr",
            "start",
            "end",
            "length",
            "strand_mode",
            "total_reads",
            "u1_pct",
            "a10_pct",
            "repeat_pct",
            "support_n",
        ],
        clusters,
    )
    de_columns = ["contrast", "cluster_id", "base_mean", "log2fc", "pvalue", "padj", "flag"]
    table(out / "de.tsv", de_columns, de)
    contrast_index = {}
    for n, contrast in enumerate(dict.fromkeys(row["contrast"] for row in de), 1):
        filename = f"contrast-{n:03d}.tsv"
        contrast_index[contrast] = filename
        table(out / filename, de_columns, (row for row in de if row["contrast"] == contrast))
    dump(out / "contrasts.json", contrast_index)
    (out / "clusters.bed").write_text(
        "".join(f"{c['chr']}\t{c['start']}\t{c['end']}\t{c['cluster_id']}\n" for c in clusters)
    )
    (out / "clusters.gff3").write_text(
        "##gff-version 3\n"
        + "".join(
            f"{c['chr']}\tpiRNA-Studio\tregion\t{c['start'] + 1}\t{c['end']}\t.\t.\t.\tID={c['cluster_id']}\n"
            for c in clusters
        )
    )
    (out / "methods.txt").write_text(methods + "\n")
    (out / "report.html").write_bytes(report(result, prov["run_id"]))
    dump(out / "results.json", result)
    (out / "read-accounting.partial.json").unlink(missing_ok=True)
    emit("Complete", 100, f"{len(clusters)} clusters across {len(samples)} samples")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("outdir")
    args = parser.parse_args()

    def log_progress(stage, percent, message):
        print(json.dumps(dict(stage=stage, percent=percent, message=message)), flush=True)

    if os.environ.get("PIRNA_ORCHESTRATOR", "direct") == "snakemake":
        if __package__:
            from .orchestrate import execute
        else:
            from orchestrate import execute
        execute(args.config, args.outdir, log_progress)
    else:
        run(inputs.load_config(args.config), args.outdir, log_progress)
