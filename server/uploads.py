"""Bounded-memory multipart reading for local sequencing-file uploads."""

import io
from email import policy
from email.parser import BytesParser

CHUNK_SIZE = 64 * 1024
MAX_HEADERS = 64 * 1024


def body_size(body):
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    position = body.tell()
    body.seek(0, 2)
    size = body.tell()
    body.seek(position)
    return size


class MultipartReader:
    def __init__(self, body, content_type):
        header = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n"
        )
        boundary = header.get_boundary()
        if not boundary or len(boundary) > 200 or any(ord(c) < 32 for c in boundary):
            raise ValueError("Supply a valid multipart boundary")
        self.marker = b"\r\n--" + boundary.encode("ascii")
        self.stream = io.BytesIO(body) if isinstance(body, (bytes, bytearray)) else body
        self.buffer = b""
        self.finished = False
        self._fill(len(self.marker) + 2)
        opening = b"--" + boundary.encode("ascii") + b"\r\n"
        if not self.buffer.startswith(opening):
            raise ValueError("Invalid multipart opening boundary")
        self.buffer = self.buffer[len(opening):]

    def _fill(self, minimum):
        while len(self.buffer) < minimum:
            chunk = self.stream.read(CHUNK_SIZE)
            if not chunk:
                raise ValueError("Incomplete upload; please select the files and retry")
            self.buffer += chunk

    def headers(self):
        while b"\r\n\r\n" not in self.buffer:
            if len(self.buffer) > MAX_HEADERS:
                raise ValueError("Upload part headers are too large")
            self._fill(len(self.buffer) + 1)
        raw, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        if len(raw) > MAX_HEADERS:
            raise ValueError("Upload part headers are too large")
        header = BytesParser(policy=policy.default).parsebytes(raw + b"\r\n\r\n")
        if header.get("Content-Transfer-Encoding", "binary").lower() not in {"binary", "8bit"}:
            raise ValueError("Upload raw files without transfer encoding")
        return header

    def copy_to(self, destination, limit=None):
        written = 0

        def write(data):
            nonlocal written
            written += len(data)
            if limit is not None and written > limit:
                raise ValueError("Upload configuration is too large")
            destination.write(data)

        keep = len(self.marker) + 2
        while True:
            index = self.buffer.find(self.marker)
            if index >= 0:
                end = index + len(self.marker)
                self._fill(end + 2)
                suffix = self.buffer[end:end + 2]
                if suffix in {b"\r\n", b"--"}:
                    write(self.buffer[:index])
                    self.buffer = self.buffer[end + 2:]
                    self.finished = suffix == b"--"
                    return written
                # A boundary-like sequence inside binary data is ordinary file data.
                write(self.buffer[:index + 2])
                self.buffer = self.buffer[index + 2:]
                continue
            if len(self.buffer) > keep:
                write(self.buffer[:-keep])
                self.buffer = self.buffer[-keep:]
            self._fill(len(self.buffer) + 1)
