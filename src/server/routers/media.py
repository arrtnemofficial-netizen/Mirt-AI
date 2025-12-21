"""Media proxy router.

Extracted from main.py to reduce God Object pattern.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from src.conf.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


@router.get("/media/proxy")
async def media_proxy(url: str, token: str | None = None) -> StreamingResponse:
    if not bool(getattr(settings, "MEDIA_PROXY_ENABLED", False)):
        raise HTTPException(status_code=404, detail="disabled")

    required_token = str(getattr(settings, "MEDIA_PROXY_TOKEN", "") or "").strip()
    if required_token and (token or "") != required_token:
        raise HTTPException(status_code=401, detail="invalid token")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="invalid url")

    host = (parsed.hostname or "").lower()
    allowed_hosts_raw = str(getattr(settings, "MEDIA_PROXY_ALLOWED_HOSTS", "") or "")
    allowed_hosts = {h.strip().lower() for h in allowed_hosts_raw.split(",") if h and h.strip()}
    if allowed_hosts and host not in allowed_hosts:
        raise HTTPException(status_code=403, detail="host not allowed")

    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        upstream = await client.get(url)

    if upstream.status_code != 200:
        raise HTTPException(status_code=502, detail=f"upstream {upstream.status_code}")

    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    if not content_type.lower().startswith("image/"):
        raise HTTPException(status_code=415, detail="not an image")

    data = upstream.content
    if len(data) > 8_000_000:
        raise HTTPException(status_code=413, detail="too large")

    headers = {
        "Cache-Control": "public, max-age=3600",
    }
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)
