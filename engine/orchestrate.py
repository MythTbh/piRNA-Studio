"""Run the dependency-graph workflow and translate scheduler events for the web monitor."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

RULES = {
    "preflight": "Preflight",
    "genome": "Genome preparation",
    "trim_and_collapse": "Adapter trimming and collapsing",
    "low_complexity": "Low-complexity filtering",
    "filter_small_rnas": "ncRNA filtering",
    "genome_mapping": "Genome mapping",
    "cluster_calling": "Cluster calling",
    "quality_control": "Sample QC",
    "consensus_counts_de_and_report": "Consensus, statistics and report",
}


def update_waterfall(state, output):
    rows = []
    for path in sorted((state / "samples").glob("*/accounting.json")):
        rows.extend(
            dict(sample_id=path.parent.name, stage=stage, reads=n)
            for stage, n in json.loads(path.read_text())
        )
    if rows and not (output / "results.json").is_file():
        temporary = output / ".waterfall.tmp"
        temporary.write_text(json.dumps(rows))
        temporary.replace(output / "read-accounting.partial.json")


def execute(config, output, emit):
    config = Path(config).resolve()
    output = Path(output).resolve()
    output.mkdir(exist_ok=True, parents=True)
    working = output.parent / ("." + output.name + "-snakemake")
    state = working / "stages"
    working.mkdir(exist_ok=True)
    env = dict(os.environ, PIRNA_STAGE_DIR=str(state))
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    command = [
        sys.executable,
        "-m",
        "snakemake",
        "--snakefile",
        str(Path(__file__).with_name("Snakefile")),
        "--cores",
        str(max(1, min(2, os.cpu_count() or 1))),
        "--scheduler",
        "greedy",
        "--shared-fs-usage",
        "input-output",
        "persistence",
        "software-deployment",
        "software-deployment-cache",
        "sources",
        "storage-local-copies",
        "--config",
        f"analysis={config}",
        f"out={output}",
    ]
    emit("Preflight", 0, "Starting the Snakemake workflow")
    stage = "Preflight"
    percent = 0
    log_path = working / "scheduler.log"
    with (
        log_path.open("w") as log,
        subprocess.Popen(
            command,
            cwd=working,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as job,
    ):
        for line in job.stdout:
            log.write(line)
            log.flush()
            rule = re.search(r"(?:local)?rule (\w+):", line)
            done = re.search(r"\d+ of \d+ steps \((\d+)%\) done", line)
            if rule and rule[1] in RULES:
                stage = RULES[rule[1]]
                emit(stage, percent, stage)
            if done:
                percent = min(int(done[1]), 99)
                update_waterfall(state, output)
                emit(stage, percent, line.strip())
        if job.wait():
            errors = [line for line in log_path.read_text().splitlines() if "Error:" in line]
            detail = errors[-1] if errors else "See scheduler.log for details."
            raise RuntimeError(f"Snakemake failed. {detail} Log: {log_path}")
    if not (output / "results.json").exists():
        raise RuntimeError("Snakemake finished without a results manifest")
    emit("Complete", 100, "Analysis outputs are ready")
