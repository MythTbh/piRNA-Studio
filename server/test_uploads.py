"""Regression checks for bounded-memory uploads and multipart binary integrity."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from .service import MAX_BODY, Service, stage_upload
from .test_service import form
from .uploads import MultipartReader, CHUNK_SIZE


class UploadTests(unittest.TestCase):
    def test_binary_boundary_like_content_and_short_reads(self):
        boundary = b"test-inputs-boundary"
        payload = bytes(range(256)) * 600 + b"\r\n--" + boundary + b"NO" + b"\x00\xff"
        headers, body = form({"samples": []}, [])
        opening = b"--" + boundary
        body = body[:-len(opening + b"--\r\n")] + opening + (
            b'\r\nContent-Disposition: form-data; name="files"; filename="reads.gz"\r\n\r\n'
        ) + payload + b"\r\n" + opening + b"--\r\n"

        class ShortReads(io.BytesIO):
            def read(self, size=-1):
                self.assert_size(size)
                return super().read(min(size, 31))

            def assert_size(self, size):
                if not 0 < size <= CHUNK_SIZE:
                    raise AssertionError("Unbounded upload read")

        with tempfile.TemporaryDirectory() as tmp:
            # Missing genome fails config validation after staging the binary file.
            with self.assertRaises(ValueError):
                stage_upload(ShortReads(body), headers["content-type"], Path(tmp))
            self.assertEqual((Path(tmp) / "inputs/reads.gz").read_bytes(), payload)

    def test_truncated_part_is_rejected(self):
        headers, body = form({"samples": []}, [])
        reader = MultipartReader(io.BytesIO(body[:-30]), headers["content-type"])
        reader.headers()
        with self.assertRaisesRegex(ValueError, "Incomplete upload"):
            reader.copy_to(io.BytesIO())

    def test_configuration_limit(self):
        headers, body = form({"large": "x" * 200}, [])
        reader = MultipartReader(body, headers["content-type"])
        reader.headers()
        with self.assertRaisesRegex(ValueError, "too large"):
            reader.copy_to(io.BytesIO(), limit=100)

    def test_limit_and_health_match_and_large_body_rejected(self):
        self.assertEqual(MAX_BODY, 4 * 1024 ** 3)
        with tempfile.TemporaryDirectory() as tmp:
            api = Service(tmp)
            try:
                health = json.loads(api.dispatch("GET", "/api/health", {})[2])
                self.assertEqual(health["max_upload_bytes"], MAX_BODY)
                with tempfile.TemporaryFile() as sparse:
                    sparse.truncate(MAX_BODY + 1)
                    response = api.dispatch("POST", "/api/preflight", {}, sparse)
                    self.assertEqual(response[0], 413)
                    self.assertIn("4 GiB", json.loads(response[2])["error"])
            finally:
                api.store.owner_lock.close()


if __name__ == "__main__":
    unittest.main()
