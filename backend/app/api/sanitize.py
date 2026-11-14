"""Strip NUL characters from JSON request bodies (audit OPT-26, F-API-1).

Postgres text can't store "\x00"; one in any free-text field (world name, Tutor message, arena
post …) used to reach the database and end the request with a 500. JSON can only carry a NUL as
the escape "\\u0000", so bodies without that sequence pass through untouched (no parsing)."""

from __future__ import annotations

import contextlib
import json
from typing import Any


def _strip(v: Any) -> Any:
    if isinstance(v, str):
        return v.replace("\x00", "")
    if isinstance(v, list):
        return [_strip(x) for x in v]
    if isinstance(v, dict):
        return {_strip(k): _strip(x) for k, x in v.items()}
    return v


class StripNul:
    """Pure ASGI middleware: rewrites the body before FastAPI validates it."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        headers = dict(scope.get("headers") or [])
        if scope["type"] != "http" or b"json" not in headers.get(b"content-type", b""):
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":  # client went away: let the app see it
                return await self.app(scope, _replay(msg, receive), send)
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        if b"\\u0000" in body:
            with contextlib.suppress(ValueError):  # not JSON after all: FastAPI answers 422
                body = json.dumps(_strip(json.loads(body)), ensure_ascii=False).encode()
        msg = {"type": "http.request", "body": body, "more_body": False}
        await self.app(scope, _replay(msg, receive), send)


def _replay(first: dict, receive):
    sent = False

    async def again():
        nonlocal sent
        if not sent:
            sent = True
            return first
        return await receive()

    return again
