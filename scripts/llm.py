#!/usr/bin/env python3
"""Switch and inspect the LLM provider (ARCHITECTURE.md §Providers). Standard library only.

    python scripts/llm.py use local|cloud|mock|auto   rewrite only the LLM_PROVIDER line in .env
                                                      (creates .env from .env.example if missing)
    python scripts/llm.py status                      provider, host, models, dim, collection, slot
    python scripts/llm.py check [--provider P]        GET /models; for local also lists pulled
                                                      Ollama models; prints `ollama pull` for gaps

The key is never printed: only "set" or "empty". `--env-file` points at another file (tests).
The worker resolves `auto` per job, so `use auto` needs no restart at slot boundaries.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.slot import TZ, current_slot, next_slot  # noqa: E402

PROVIDERS = ("local", "cloud", "mock", "auto")
LINE = re.compile(r"^\s*LLM_PROVIDER\s*=.*$", re.MULTILINE)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def use(path: Path, provider: str) -> str:
    if not path.exists():
        template = path.with_name(".env.example")
        if not template.exists():
            template = ROOT / ".env.example"
        shutil.copyfile(template, path)
        print(f"created {path.name} from .env.example")
    text = path.read_text(encoding="utf-8")
    new = f"LLM_PROVIDER={provider}"
    text = LINE.sub(new, text, count=1) if LINE.search(text) else text.rstrip("\n") + f"\n{new}\n"
    path.write_text(text, encoding="utf-8")
    return provider


def slot_line(env: dict[str, str]) -> tuple[bool, str]:
    group = env.get("LLM_SLOT_GROUP", "A").upper()
    now = datetime.now(TZ)
    live = current_slot(now, group)
    if live:
        return True, f"group {group}: LIVE until {live.end:%H:%M}".replace(" 00:00", " 24:00")
    nxt = next_slot(now, group)
    return False, f"group {group}: not live, next {nxt.label() if nxt else 'none'}"


def effective(env: dict[str, str]) -> tuple[str, str]:
    """(configured, what a job would use now) — mirrors app/gateway/providers.py, minus the
    401-since-slot-start check, which needs the database."""
    configured = env.get("LLM_PROVIDER", "mock")
    if configured != "auto":
        return configured, configured
    live, _ = slot_line(env)
    cloud_ok = bool(env.get("CLOUD_API_KEY") and env.get("CLOUD_BASE_URL"))
    return configured, "cloud" if live and cloud_ok else "local"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def status(env: dict[str, str]) -> None:
    configured, now = effective(env)
    p = now.upper()
    base = env.get(f"{p}_BASE_URL", "")
    host = re.sub(r"^https?://", "", base).split("/")[0] or "(unset)"
    key = "set" if env.get(f"{p}_API_KEY") else "empty"
    prefix = env.get("QDRANT_COLLECTION_PREFIX", "hack-04-chunks")
    emb = env.get(f"{p}_EMBEDDING_MODEL", "?")
    print(f"provider     {configured}" + (f" → {now} right now" if configured == "auto" else ""))
    print(f"host         {host}   key: {key}")
    print(f"compact      {env.get(f'{p}_MODEL_COMPACT', '?')}")
    print(f"mid          {env.get(f'{p}_MODEL_MID', '?')}")
    print(f"embeddings   {emb} ({env.get(f'{p}_EMBEDDING_DIM', '?')} dims)")
    print(f"collection   {prefix}-{now}-{slug(emb)}")
    print(f"slot         {slot_line(env)[1]}")
    if configured == "auto":
        print("note         a 401 'Key is blocked' in this slot also switches jobs to local")


def http_json(url: str, key: str = "", timeout: float = 10):
    req = urllib.request.Request(url)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return e.code, body.replace(key, "***") if key else body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def check(env: dict[str, str], provider: str | None) -> int:
    _, now = effective(env)
    provider = provider or now
    p = provider.upper()
    base = env.get(f"{p}_BASE_URL", "").rstrip("/")
    key = env.get(f"{p}_API_KEY", "")
    if not base:
        print(f"{p}_BASE_URL is empty")
        return 1
    status_code, payload = http_json(f"{base}/models", key)
    if status_code != 200:
        print(f"GET /models → {status_code or 'no answer'}: {payload}")
        if provider == "cloud":
            print("outside our slot the key answers 401 'Key is blocked' (python scripts/slot.py)")
        if provider == "local":
            print("is Ollama running? start it, or run scripts/setup_ollama.ps1")
        return 1
    ids = [m.get("id") for m in payload.get("data", []) if isinstance(m, dict)]
    print(f"{provider}: {len(ids)} models — " + ", ".join(ids))
    if provider != "local":
        return 0
    root = re.sub(r"/v1/?$", "", base)
    code, tags = http_json(f"{root}/api/tags")
    pulled = {m.get("name") for m in tags.get("models", [])} if code == 200 else set(ids)
    needed = [env.get(f"LOCAL_{k}") for k in ("MODEL_COMPACT", "MODEL_MID", "EMBEDDING_MODEL")]
    missing = [m for m in needed if m and m not in pulled and f"{m}:latest" not in pulled]
    if missing:
        print("missing: ollama pull " + " ".join(missing))
        return 1
    print("all local models pulled: " + ", ".join(m for m in needed if m))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows pipes default to cp1252: never crash on →
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("use")
    u.add_argument("provider", choices=PROVIDERS)
    sub.add_parser("status")
    c = sub.add_parser("check")
    c.add_argument("--provider", choices=("local", "cloud", "mock"))
    a = ap.parse_args(argv)

    if a.cmd == "use":
        use(a.env_file, a.provider)
        print(f"LLM_PROVIDER={a.provider} — the worker picks it up for the next job")
        return 0
    env = read_env(a.env_file)
    if not env:
        print(f"{a.env_file} not found — run: python scripts/llm.py use mock")
        return 1
    if a.cmd == "status":
        status(env)
        return 0
    return check(env, a.provider)


if __name__ == "__main__":
    sys.exit(main())
