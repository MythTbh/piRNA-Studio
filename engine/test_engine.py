import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import inputs, science, pipeline


class EvidenceTests(unittest.TestCase):
    def test_fractional_and_unique(self):
        read = "TAGAAAAAACCGGGGTTTTGCAAC"
        genome = {"A": read + "N" * 10 + read, "B": science.rc(read)}
        hits = science.portable_align({read: 12}, genome)
        self.assertEqual(len(hits), 3)
        intervals = [("A", 0, len(read)), ("B", 0, len(read))]
        calls = {"s": intervals}
        for mode, expected in [("fractional", [4, 4]), ("unique", [0, 0])]:
            rows, integer = science.counts_and_clusters(
                intervals, {"s": hits}, calls, {"count_mode": mode}, []
            )
            self.assertEqual([x["total_reads"] for x in rows], expected)
            self.assertEqual(sum(r["s"] for r in integer.values()), 0)

    def test_overlapping_replicates_not_adjacent_regions(self):
        samples = [dict(sample_id=str(n), condition="C") for n in range(3)]
        calls = {"0": [("chr", 0, 20), ("chr", 10, 30)], "1": [("chr", 20, 40)], "2": [("chr", 40, 60)]}
        self.assertEqual(science.consensus(calls, samples, 2), [("chr", 20, 30)])

    def test_reciprocal_overlap_and_union_jaccard(self):
        regions = [dict(chr="a", start=0, end=100, length=100, cluster_id="c")]
        stats = science.validate(
            regions, [("a", 10, 70, "r1"), ("a", 50, 120, "r2"), ("a", 200, 210, "miss")]
        )
        self.assertEqual(stats["precision"], 1)
        self.assertAlmostEqual(stats["recall"], 2 / 3)
        self.assertAlmostEqual(stats["jaccard"], 90 / 130)
        self.assertEqual(stats["missed"], ["miss"])

    def test_reverse_five_prime_off_by_one(self):
        hits = [
            science.Hit("C", 100, 126, "+", "T" * 26, 3, 1),
            science.Hit("C", 84, 110, "-", "A" * 26, 7, 1),
        ]
        overlap, z, partners = science.pingpong(hits, 24)
        self.assertEqual(overlap[10], 21)
        self.assertEqual(overlap[9], 0)
        self.assertGreater(z, 1.65)
        self.assertEqual(len(partners), 2)

    def test_sample_validation(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "g").write_text(">x\n" + "C" * 100 + "\n")
            (folder / "q").write_bytes(gzip.compress(b"@bad\nATT\n+\n!\n"))
            sample = dict(sample_id="bad", fastq_path=str(folder / "q"), condition="c", replicate=1)
            checks = inputs.preflight(dict(genome=str(folder / "g"), samples=[sample]))
            self.assertTrue(
                any(r["severity"] == "error" and "record 1" in r["message"] for r in checks)
            )
            (folder / "ref").write_text("wrong\t0\t3\n")
            with self.assertRaises(ValueError):
                inputs.bed(folder / "ref", {"x": "CCC"})

    def test_synthetic_end_to_end(self):
        cfg = inputs.load_config(Path(__file__).parent / "example" / "config.json")
        cfg["params"]["de_method"] = "descriptive"
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = pipeline.run(cfg, out)
            self.assertEqual(len(result["clusters"]), 18)
            self.assertEqual(len(result["de"]), 18)
            self.assertEqual(len(result["validation"]["matched"]), 17)
            self.assertTrue(all(x["pvalue"] is None for x in result["de"]))
            self.assertEqual(
                result["clusters"], json.loads((out / "results.json").read_text())["clusters"]
            )
            self.assertTrue((out / "counts.tsv").is_file())
            self.assertIn("Discovered clusters", (out / "report.html").read_text())
            self.assertFalse((out / "read-accounting.partial.json").exists())
            self.assertTrue(all(c["pingpong_z"] > 1.65 for c in result["qc"]))
            for s in result["samples"]:
                n = [r["reads"] for r in result["accounting"] if r["sample_id"] == s["sample_id"]]
                self.assertEqual(n, sorted(n, reverse=True))


if __name__ == "__main__":
    unittest.main()
