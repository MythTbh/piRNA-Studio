"""Local API regression tests. Run with python3 -m unittest server.test_service."""

import io
import json
import random
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from .service import Service, stage_upload


def form(config, inputs):
    sep = "test-inputs-boundary"

    def field(name, data, filename=None):
        fname = f'; filename="{filename}"' if filename is not None else ""
        return (
            f'--{sep}\r\nContent-Disposition: form-data; name="{name}"{fname}\r\n\r\n'.encode()
            + data
            + b"\r\n"
        )

    data = field("config", json.dumps(config).encode())
    for name, contents in inputs:
        data += field("files", contents.encode(), name)
    return {
        "content-type": f"multipart/form-data; boundary={sep}"
    }, data + f"--{sep}--\r\n".encode()


class LocalApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = Service(self.tmp.name)
        self.config = {
            "genome": "chrom.fa",
            "reference": "reference.bed",
            "samples": [
                {
                    "sample_id": "sample1",
                    "condition": "case",
                    "replicate": "1",
                    "library_kit": "TruSeq",
                    "fastq_path": "sample.fq",
                }
            ],
            "params": {
                "min_cluster_size": 55,
                "min_loci": 3,
                "de_method": "descriptive",
            },
        }
        rng = random.Random(7)
        genome = "".join(rng.choices("ACGT", k=1200))
        reads = [
            genome[i : i + 26] + "TGGAATTCTCGGGTGCCAAGG" for i in range(120, 280, 10)
        ]
        fastq = "".join(
            f"@r{i}\n{seq}\n+\n{'I' * len(seq)}\n" for i, seq in enumerate(reads)
        )
        self.inputs = [
            ("chrom.fa", ">chr1\n" + genome + "\n"),
            ("reference.bed", "chr1\t120\t296\ttarget\n"),
            ("sample.fq", fastq),
        ]

    def tearDown(self):
        self.api.store.owner_lock.close()
        self.tmp.cleanup()

    def test_inputs_must_stay_inside_job(self):
        headers, body = form(self.config, [("../escape", "bad")])
        with tempfile.TemporaryDirectory() as stage:
            with self.assertRaises(ValueError):
                stage_upload(body, headers["content-type"], Path(stage))

    def test_http_response_framing(self):
        from .__main__ import make_handler

        class Connection:
            sent = bytearray()

            def makefile(self, *args):
                return io.BytesIO(
                    b"GET /api/health HTTP/1.0\r\nHost: localhost\r\n\r\n"
                )

            def sendall(self, raw):
                self.sent.extend(raw)

        sock = Connection()
        handler = make_handler(self.api)
        handler.log_message = lambda *args: None
        handler(sock, ("127.0.0.1", 1), None)
        headers, body = bytes(sock.sent).split(b"\r\n\r\n", 1)
        self.assertIn(b"200 OK", headers)
        self.assertIn(f"Content-Length: {len(body)}".encode(), headers)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_cross_origin_submit_is_rejected(self):
        status, _, _ = self.api.dispatch(
            "POST", "/api/runs", {"origin": "http://other", "host": "localhost"}
        )
        self.assertEqual(status, 403)

    def test_end_to_end(self):
        headers, body = form(self.config, self.inputs)
        response = self.api.dispatch("POST", "/api/preflight", headers, body)
        self.assertEqual(response[0], 200, response)
        self.assertFalse(json.loads(response[2])["blocking"])
        code, _, payload = self.api.dispatch("POST", "/api/runs", headers, body)
        self.assertEqual(code, 202, payload)
        rid = json.loads(payload)["run_id"]
        resource = f"/api/runs/{rid}/"
        for _ in range(200):
            status = json.loads(self.api.dispatch("GET", resource + "status", {})[2])
            if status["status"] in ("failed", "completed"):
                break
            time.sleep(0.05)
        self.assertEqual(status["status"], "completed", status)
        get = lambda name: self.api.dispatch("GET", resource + name, {})
        result = json.loads(get("results")[2])
        self.assertGreaterEqual(len(result["clusters"]), 1)
        self.assertEqual(
            json.loads(get("clusters?min_reads=1")[2])["total"], len(result["clusters"])
        )
        self.assertEqual(json.loads(get("qc")[2])["qc"], result["qc"])
        for action in ("zip", "reproduce"):
            code, _, payload = get(f"export?format={action}")
            self.assertEqual(code, 200)
            with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
                self.assertIn(
                    "report.html" if action == "zip" else "inputs/sample.fq",
                    bundle.namelist(),
                )
        self.assertIn(b"piRNA Studio", get("export?format=html")[2])
        self.assertEqual(
            json.loads(self.api.dispatch("POST", resource + "cancel", {})[2])["status"],
            "completed",
        )

    def test_queued_cancel(self):
        headers, body = form(self.config, self.inputs)
        # Hold the sole compute slot to cancel before the worker launches.
        with self.api.store.compute_slot:
            code, _, payload = self.api.dispatch("POST", "/api/runs", headers, body)
            self.assertEqual(code, 202, payload)
            rid = json.loads(payload)["run_id"]
            resource = f"/api/runs/{rid}/"
            self.assertEqual(
                json.loads(self.api.dispatch("GET", resource + "status", {})[2])[
                    "status"
                ],
                "queued",
            )
            self.assertEqual(
                json.loads(self.api.dispatch("POST", resource + "cancel", {})[2])[
                    "status"
                ],
                "cancelled",
            )
        self.assertEqual(self.api.dispatch("GET", resource + "results", {})[0], 409)
        time.sleep(0.05)
        status = json.loads(self.api.dispatch("GET", resource + "status", {})[2])
        self.assertEqual(status["status"], "cancelled")

    def test_invalid_sample_blocks_run(self):
        self.config["samples"][0]["fastq_path"] = "missing.fq"
        headers, body = form(self.config, self.inputs)
        self.assertTrue(
            json.loads(self.api.dispatch("POST", "/api/preflight", headers, body)[2])[
                "blocking"
            ]
        )
        self.assertEqual(self.api.dispatch("POST", "/api/runs", headers, body)[0], 422)
        self.assertEqual(self.api.store.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
