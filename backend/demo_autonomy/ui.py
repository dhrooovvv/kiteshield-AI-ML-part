"""Static demo console on 3001; proxy can reach only this demo's 8001 API."""

from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(docs_url=None, openapi_url=None)


@app.api_route("/demo/{path:path}", methods=["GET", "POST", "PUT"])
async def proxy(path: str, request: Request):
    # No configurable destination, redirects, query forwarding or wallet credentials.
    if ".." in path or ":" in path or "//" in path:
        return Response(status_code=400)
    async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
        try:
            result = await client.request(
                request.method,
                "http://127.0.0.1:8001/" + path,
                content=await request.body(),
                headers={
                    "Authorization": request.headers.get("Authorization", ""),
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError:
            return Response(
                '{"detail":"Demo backend unavailable on port 8001"}',
                status_code=503,
                media_type="application/json",
            )
    return Response(
        result.content,
        status_code=result.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/", StaticFiles(directory=Path(__file__).with_name("ui"), html=True))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3001)
