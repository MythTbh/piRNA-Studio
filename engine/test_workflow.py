"""Integration checks for Snakemake and for the optional pinned research tools."""

import json
import os
from pathlib import Path
import random
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from . import external, inputs, pipeline

HERE = Path(__file__).parent
NATIVE = all(
    Path(os.environ.get(k, "")).is_file() for k in ("DUSTER_PL", "SRNAMAPPER_PL", "PROTRAC_PL")
) and shutil.which("cutadapt")


def positive_control(folder):
    # One planted high-density 1U locus and sparse independent background mappings.
    rng = random.Random(77)
    bases = "".join(rng.choices("ACGT", k=2_500_000))
    inputs.write_genome(folder / "genome.fa", {"S": bases})
    reads = [bases[i : i + 28] for i in range(200_000, 211_000) if bases[i] == "T"]
    reads.extend(bases[i : i + 27] for i in range(350_000, 2_400_000, 1000))
    with (folder / "reads.fastq").open("w") as stream:
        for i, seq in enumerate(reads):
            full = seq + inputs.ADAPTERS["truseq"]
            stream.write(f"@r{i}\n{full}\n+\n{'I' * len(full)}\n")
    (folder / "ref.bed").write_text("S\t200000\t211000\tplanted\n")
    config = dict(
        genome="genome.fa",
        reference="ref.bed",
        params={"backend": "protrac"},
        samples=[
            dict(
                sample_id="sample",
                condition="synthetic",
                replicate=1,
                library_kit="TruSeq",
                fastq_path="reads.fastq",
            )
        ],
    )
    (folder / "config.json").write_text(json.dumps(config))
    return folder / "config.json"


def snake(cfg, out):
    subprocess.run(
        [
            "snakemake",
            "-s",
            str(HERE / "Snakefile"),
            "--cores",
            "2",
            "--shared-fs-usage",
            "input-output",
            "persistence",
            "software-deployment",
            "software-deployment-cache",
            "sources",
            "storage-local-copies",
            "--config",
            f"analysis={cfg}",
            f"out={out}",
        ],
        cwd=out.parent,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


class WorkflowTests(unittest.TestCase):
    def test_native_table_coordinates(self):
        sample = "Cluster 1\tLocation: S\tCoordinates: 200002-211025\tSize [bp]: 11024\nTotal size of 1 predicted piRNA clusters: 11024 bp"
        self.assertEqual(external.parse_calls(sample), [("S", 200001, 211025)])
        with self.assertRaises(RuntimeError):
            external.parse_calls(sample.replace("Total size of 1", "Total size of 2"))

    def test_perl_fasta_line_wrapping(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.fa"
            originals = {"a": "A" * 259, "b": "GT" * 109}
            inputs.write_genome(path, originals)
            self.assertEqual(inputs.genome(path), originals)
            self.assertLessEqual(max(map(len, path.read_text().splitlines())), 80)

    @unittest.skipUnless(shutil.which("snakemake"), "Install the workflow environment")
    def test_snakemake_portable(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = inputs.load_config(HERE / "example" / "config.json")
            config["samples"] = config["samples"][:1]
            (folder / "cfg.json").write_text(json.dumps(config))
            out = folder / "analysis"
            snake(folder / "cfg.json", out)
            self.assertEqual(len(json.loads((out / "results.json").read_text())["clusters"]), 18)
            mtime = (out / "results.json").stat().st_mtime_ns
            snake(folder / "cfg.json", out)
            self.assertEqual((out / "results.json").stat().st_mtime_ns, mtime)

    @unittest.skipUnless(
        NATIVE and shutil.which("snakemake"), "Install the pinned Perl tools, cutadapt, Snakemake"
    )
    def test_snakemake_external_positive_control(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            cfg = positive_control(folder)
            out = folder / "analysis"
            snake(cfg, out)
            result = json.loads((out / "results.json").read_text())
            self.assertEqual(len(result["clusters"]), 1)
            self.assertGreater(result["validation"]["jaccard"], 0.98)
            self.assertEqual(result["validation"]["recall"], 1)
            self.assertIn("2.4.2", result["provenance"]["tools"]["PROTRAC_PL"])
            direct = pipeline.run(inputs.load_config(cfg), folder / "direct")
            self.assertEqual(result["clusters"], direct["clusters"])
            self.assertEqual(result["qc"], json.loads((folder / "direct" / "qc.json").read_text()))


if __name__ == "__main__":
    unittest.main()
