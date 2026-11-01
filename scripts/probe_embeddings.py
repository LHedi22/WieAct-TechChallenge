#!/usr/bin/env python3
"""Find the cloud embeddings model name (in-slot only). `/v1/models` lists chat models only, so
this tries one unknown name (the 400 body may list the valid ones), then a short candidate list,
stopping at the first 200. At most 1 + len(CANDIDATES) calls on the embeddings quota.

    python3 scripts/probe_embeddings.py              # candidates below
    python3 scripts/probe_embeddings.py name1 name2  # try these names instead

Prints the .env lines to paste; never prints the key. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_models as pm  # noqa: E402  (shares http, redact, read_env, cosine)

CANDIDATES = [
    "bge-m3",
    "BAAI/bge-m3",
    "nomic-embed-text",
    "multilingual-e5-large",
    "intfloat/multilingual-e5-large",
    "text-embedding-3-small",
    "mxbai-embed-large",
    "all-minilm",
    "jina-embeddings-v3",
]
TEXTS = [
    "limit of a function as x approaches a",
    "نهاية الدالة عندما يقترب x من a",
    "a recipe for chocolate cake",
]


def main() -> int:
    env = pm.read_env()
    base = (env.get("CLOUD_BASE_URL") or "").rstrip("/")
    key = env.get("CLOUD_API_KEY", "")
    if not base or not key:
        print("Set CLOUD_BASE_URL and CLOUD_API_KEY in .env (a human fills the key).")
        return 1
    pm._secret = key

    status, _, p, _ = pm.http("POST", f"{base}/embeddings", key, {"model": "no-such-model", "input": ["hi"]})
    print(f"▶ unknown model → HTTP {status}: {pm.redact(json.dumps(p) if not isinstance(p, str) else p)[:600]}")
    if status == 401:
        print("Key is blocked (outside our slot?). Stopping.")
        return 1

    for m in sys.argv[1:] or CANDIDATES:
        status, _, p, dt = pm.http("POST", f"{base}/embeddings", key, {"model": m, "input": TEXTS})
        if status == 200 and isinstance(p, dict) and p.get("data"):
            v = [d["embedding"] for d in p["data"]]
            cross, unrelated = pm.cosine(v[0], v[1]), pm.cosine(v[0], v[2])
            print(f"▶ {m}: dim {len(v[0])}, EN↔AR {cross:.2f} vs unrelated {unrelated:.2f}, {dt:.1f}s")
            print("\nPaste into .env (never commit it):")
            print(f"  CLOUD_EMBEDDING_MODEL={m}\n  CLOUD_EMBEDDING_DIM={len(v[0])}")
            return 0
        body = pm.redact(json.dumps(p) if not isinstance(p, str) else p)
        print(f"▶ {m}: HTTP {status} {body[:200]}")
    print("\nNo candidate worked: ask the organisers (wie.act@ieee.tn) for the embeddings model name.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
