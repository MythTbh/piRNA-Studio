"""Optional FastAPI entry point. Launch one Uvicorn worker per data directory."""

import os
import tempfile

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .service import MAX_BODY, UPLOAD_LIMIT_ERROR, Service, serialized

app = FastAPI(title="piRNA Studio", docs_url=None, redoc_url=None, openapi_url=None)
service = Service(os.environ.get("PIRNA_DATA", ".pirna-data"))


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def route(path: str, request: Request):
    with tempfile.TemporaryFile(dir=service.store.directory) as body:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                code, headers, payload = serialized({"error": UPLOAD_LIMIT_ERROR}, 413)
                break
            await run_in_threadpool(body.write, chunk)
        else:
            body.seek(0)
            target = "/" + path + ("?" + request.url.query if request.url.query else "")
            code, headers, payload = await run_in_threadpool(
                service.dispatch, request.method, target, dict(request.headers), body
            )
    headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    return Response(payload, status_code=code, headers=headers)
