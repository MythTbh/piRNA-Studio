"""Run a loopback piRNA Studio service with the Python standard library."""

import argparse
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import MAX_BODY, UPLOAD_LIMIT_ERROR, Service, serialized


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.handle_api()

        def do_POST(self):
            self.handle_api()

        def handle_api(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > MAX_BODY:
                    result = serialized(
                        {"error": UPLOAD_LIMIT_ERROR}, 413
                    )
                elif size < 0 or self.headers.get("Transfer-Encoding"):
                    result = serialized({"error": "Supply a valid Content-Length"}, 400)
                else:
                    headers = {k.lower(): v for k, v in self.headers.items()}
                    if self.command == "POST":
                        with tempfile.TemporaryFile(dir=service.store.directory) as body:
                            remaining = size
                            while remaining:
                                chunk = self.rfile.read(min(64 * 1024, remaining))
                                if not chunk:
                                    raise ValueError("Incomplete upload; please retry")
                                body.write(chunk)
                                remaining -= len(chunk)
                            body.seek(0)
                            result = service.dispatch(self.command, self.path, headers, body)
                    else:
                        result = service.dispatch(self.command, self.path, headers)
            except ValueError as exc:
                result = serialized({"error": str(exc)}, 400)
            except Exception as exc:
                print(f"Request failed: {exc}", file=sys.stderr, flush=True)
                result = serialized(
                    {
                        "error": "The local service could not complete this request. Check the server console."
                    },
                    500,
                )
            status, headers, data = result
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="piRNA Studio local workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data", default=os.environ.get("PIRNA_DATA", ".pirna-data"))
    args = parser.parse_args()
    service = Service(args.data)
    with ThreadingHTTPServer((args.host, args.port), make_handler(service)) as server:
        print(
            f"piRNA Studio is ready at http://{args.host}:{server.server_port}",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            for run_id in list(service.store.workers):
                service.store.cancel(run_id)


if __name__ == "__main__":
    main()
