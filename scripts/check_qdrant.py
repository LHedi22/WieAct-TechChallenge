#!/usr/bin/env python3
"""Check a hosted Qdrant (e.g. our Qdrant Cloud cluster) before putting it in the deploy.

    export QDRANT_URL=https://<cluster>.cloud.qdrant.io:6333
    export QDRANT_API_KEY=...            # in your own terminal; never in a chat or a commit
    python3 scripts/check_qdrant.py

Reads only the environment (not .env, so dev keeps its local Qdrant), lists the collections and
never prints the key. The app creates its collection itself on first use
(`{QDRANT_COLLECTION_PREFIX}-cloud-{embedding slug}`, sized by CLOUD_EMBEDDING_DIM); don't create
it by hand. Standard library only; on macOS add SSL_CERT_FILE=/etc/ssl/cert.pem if TLS fails.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    url = os.environ.get("QDRANT_URL", "").rstrip("/")
    key = os.environ.get("QDRANT_API_KEY", "")
    if not url.startswith("https://") or not key:
        print("Set QDRANT_URL (https://…:6333) and QDRANT_API_KEY in this terminal first.")
        return 1
    req = urllib.request.Request(f"{url}/collections", headers={"api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            names = [c["name"] for c in json.load(r)["result"]["collections"]]
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {'wrong or read-only API key' if e.code in (401, 403) else e.reason}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Can't reach {url}: {type(e).__name__}: {str(e).replace(key, '***')}")
        return 1
    print(f"OK: {url} answers; collections: {', '.join(names) or '(none yet; the app creates its own)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
