"""Logging pass-through in front of the LLM (audit only, stdlib only).

Routes:
  /mock/...   -> MOCK_UPSTREAM   (default http://mock-llm:9000)
  /ollama/... -> OLLAMA_UPSTREAM (default http://host.docker.internal:11434)
Anything else is refused with 502, so a misconfigured base URL can never reach a third host.

Writes one JSON line per request to LOG_FILE: ts, route, path, model, status, sha256 of the
request body (minus volatile fields), in-flight count at start, latency. Never logs bodies or
Authorization headers.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAMS = {
    "mock": os.environ.get("MOCK_UPSTREAM", "http://mock-llm:9000"),
    "ollama": os.environ.get("OLLAMA_UPSTREAM", "http://host.docker.internal:11434"),
}
LOG_FILE = os.environ.get("LOG_FILE", "/logs/llm-calls.jsonl")
PORT = int(os.environ.get("PORT", "9100"))

_lock = threading.Lock()
_in_flight = {"n": 0, "max": 0}
HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "host", "content-encoding"}


def _write(rec: dict) -> None:
    with _lock, open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _proxy(self, method: str) -> None:
        parts = self.path.split("/", 2)
        route = parts[1] if len(parts) > 1 else ""
        if self.path == "/_stats":
            body = json.dumps(_in_flight).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route not in UPSTREAMS:
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()
            _write({"ts": time.time(), "route": route, "path": self.path, "status": 502, "refused": True})
            return
        rest = "/" + (parts[2] if len(parts) > 2 else "")
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        model, h = None, None
        if raw:
            try:
                j = json.loads(raw)
                model = j.get("model")
                h = hashlib.sha256(json.dumps(j, sort_keys=True).encode()).hexdigest()[:16]
            except Exception:
                h = hashlib.sha256(raw).hexdigest()[:16]
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        req = urllib.request.Request(UPSTREAMS[route] + rest, data=raw or None, headers=headers, method=method)
        with _lock:
            _in_flight["n"] += 1
            started_with = _in_flight["n"]
            _in_flight["max"] = max(_in_flight["max"], started_with)
        t0 = time.time()
        status, rh, body = 502, {}, b""
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                status, rh, body = r.status, dict(r.headers.items()), r.read()
        except urllib.error.HTTPError as e:
            status, rh, body = e.code, dict(e.headers.items()), e.read()
        except Exception as e:  # upstream down
            status, body = 599, json.dumps({"error": f"llm_logger upstream error: {type(e).__name__}"}).encode()
        finally:
            with _lock:
                _in_flight["n"] -= 1
        _write(
            {
                "ts": round(t0, 3),
                "route": route,
                "path": rest.split("?")[0],
                "model": model,
                "status": status,
                "body_sha": h,
                "in_flight": started_with,
                "fault": self.headers.get("X-Mock-Fault"),
                "ms": int((time.time() - t0) * 1000),
            }
        )
        self.send_response(status)
        for k, v in rh.items():
            if k.lower() not in HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    print(f"llm_logger on :{PORT} -> {UPSTREAMS}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
