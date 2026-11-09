"""Shared HTTP helper so every server doesn't reimplement client setup."""
from __future__ import annotations

from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_HEADERS = {"User-Agent": "ai-agent-mcp/1.0 (+https://github.com/)"}


async def get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={**_HEADERS, **(headers or {})}) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={**_HEADERS, **(headers or {})}) as client:
        resp = await client.request(method, url, params=params, json=json_body)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {"status": "ok"}
        return resp.json()
