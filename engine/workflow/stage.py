"""Snakemake stage entry point. Reads only outputs from completed dependencies."""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import astuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import external
import inputs
import pipeline
import science


def main(action, config_path, root, sid):
    config = inputs.load_config(config_path)
    params = {**inputs.DEFAULTS, **config.get("params", {})}
    portable = params["backend"] == "portable"
    state = Path(os.environ.get("PIRNA_STAGE_DIR", root / "workflow"))
    state.mkdir(exist_ok=True, parents=True)
    if action == "check":
        checks = inputs.preflight(config, check_tools=False)
        bad = [c["message"] for c in checks if c["severity"] == "error"]
        if bad:
            raise ValueError("; ".join(bad))
        pipeline.dump(state / "checks.json", checks)
        return
    if action == "genome":
        inputs.write_genome(state / "genome.fa", inputs.genome(config["genome"]))
        return
    if action == "finish":
        records = {
            s["sample_id"]: state / "samples" / s["sample_id"] / "profile.json"
            for s in config["samples"]
        }
        pipeline.run(config, root, prepared=records)
        return
    sample = next(s for s in config["samples"] if s["sample_id"] == sid)
    directory = state / "samples" / sid
    directory.mkdir(exist_ok=True, parents=True)

    def read(name):
        return json.loads((directory / (name + ".json")).read_text())

    def write(name, data):
        pipeline.dump(directory / (name + ".json"), data)

    reference = state / "genome.fa"
    if action == "trim":
        total, hist, collapsed = pipeline.trim_collapse(sample, params, directory)
        ver = (
            None if portable else subprocess.check_output(["cutadapt", "--version"], text=True).strip()
        )
        write("trim", dict(total=total, hist=hist, counts=collapsed, cutadapt_version=ver))
    elif action == "dust":
        write("dust", pipeline.complexity(read("trim")["counts"], params, directory))
    elif action == "filter":
        refs = {k: inputs.genome(v, rna=True) for k, v in config.get("ncrna", {}).items()}
        kept, stages = pipeline.ncrna_filter(read("dust"), refs)
        write("filter", dict(counts=kept, stages=stages))
    elif action == "map":
        counts = read("filter")["counts"]
        if portable:
            hits = science.portable_align(counts, inputs.genome(reference))
        else:
            hits = external.align(counts, reference, directory)
        write("map", [astuple(h) for h in hits])
    elif action == "call":
        if portable:
            calls = science.portable_calls([science.Hit(*r) for r in read("map")], params)
        else:
            calls = external.call(reference, directory, params)
        write("calls", calls)
    elif action == "qc":
        row = read("trim")
        hist = Counter({int(k): v for k, v in row["hist"].items()})
        raw = read("map")
        metrics, partners = pipeline.qc_profile(
            sid, row["total"], hist, row["counts"], [science.Hit(*h) for h in raw], params
        )
        stages = [
            ("Input", row["total"]),
            ("Pairs merged" if inputs.is_paired(sample) else "Adapter trimmed", sum(hist.values())),
            ("Length filtered", sum(row["counts"].values())),
            ("Complexity filtered", sum(read("dust").values())),
            *read("filter")["stages"],
            ("Genome mapped", metrics["mapped_reads"]),
        ]
        write(
            "profile",
            dict(
                hits=raw,
                calls=read("calls"),
                qc=metrics,
                partners=partners,
                accounting=stages,
                cutadapt_version=row["cutadapt_version"],
            ),
        )
        temporary = directory / "accounting.tmp"
        pipeline.dump(temporary, stages)
        temporary.replace(directory / "accounting.json")
        dest = root / "intermediate" / sid
        dest.mkdir(exist_ok=True, parents=True)
        for path in directory.rglob("*"):
            if path.is_file() and path.name in {
                "aligned.map",
                "results.table",
                "commands.log",
                "filtered.fa",
                "collapsed.fa",
            }:
                shutil.copy(path, dest / path.name)
    else:
        raise ValueError(f"Unknown action {action}")


if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2],
        Path(sys.argv[3]).resolve(),
        sys.argv[4] if len(sys.argv) > 4 else None,
    )
