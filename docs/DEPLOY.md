# Deploy — Railway (API + worker + Postgres) · Vercel (frontend) · Qdrant Cloud

A human does these steps: they need accounts and secrets. Never paste a secret into the repo,
a chat, a screenshot or the video. Variable **names** are listed here; the values go only into
each platform's secret settings. Why this shape: DECISIONS.md (2026-10-30 · M8 deploy).

```
browser ──▶ Vercel (static React build)
              └─ /api/*  rewrite ──▶ Railway "app": alembic → worker (1 process) + uvicorn
                                           ├─ Railway Postgres
                                           ├─ Railway volume /data (uploads)
                                           ├─ Qdrant Cloud (vectors)
                                           ├─ Railway "ollama" (bge-m3 embeddings, private network)
                                           └─ EdNova platform (chat, our slot only)
```

## Embeddings
Our key has no embeddings model, so a second Railway service runs **Ollama with `bge-m3`** for
embeddings only (DECISIONS.md 2026-10-31). Chat stays on the platform.

## 1. Qdrant Cloud
Create a free cluster → copy its URL and an API key → keep them for step 2
(`QDRANT_URL`, `QDRANT_API_KEY`). Check them from your own terminal with
`python3 scripts/check_qdrant.py` (it reads the two variables from the environment and never prints
the key). The app creates the collection
`{QDRANT_COLLECTION_PREFIX}-cloud-{embedding slug}` on first use.

## 2. Railway
1. New project → **Deploy from GitHub repo** → this repo. Service settings: **Root directory**
   `backend`. If `backend/railway.toml` isn't picked up automatically, set **Config file path**
   to `/backend/railway.toml`. It builds `backend/Dockerfile` (Tesseract included) and starts
   `sh start-prod.sh`.
2. **+ New → Database → PostgreSQL.**
   **+ New → GitHub repo** (same repo) → name the service **`ollama`** → Root directory
   `deploy/ollama` (it builds `deploy/ollama/Dockerfile`). Add a volume mounted at
   `/root/.ollama` so the model (~1.2 GB) is downloaded once. Don't generate a public domain for
   it. Its log shows `ollama ready with bge-m3` when it's up. It needs about 2 GB of RAM.
3. Service → **Volumes** → add one mounted at `/data`. If the container can't write to it, set
   `RAILWAY_RUN_UID=0`.
4. Service → **Variables** (names from `.env.example`):

   | Variable | Value |
   | --- | --- |
   | `APP_ENV` | `production` (only `LLM_PROVIDER=cloud` is accepted) |
   | `LLM_PROVIDER` | `cloud` |
   | `CLOUD_BASE_URL`, `CLOUD_API_KEY` | platform URL · the hack-04 key |
   | `CLOUD_MODEL_COMPACT`, `CLOUD_MODEL_MID` | `llama3.2-3b`, `llama3.1-8b` (DECISIONS.md) |
   | `EMBED_PROVIDER` | `local` |
   | `LOCAL_BASE_URL` | `http://ollama.railway.internal:11434/v1` (if it can't connect, check the private domain on the ollama service) |
   | `LOCAL_EMBEDDING_MODEL`, `LOCAL_EMBEDDING_DIM` | `bge-m3`, `1024` |
   | `LLM_DISABLE_THINKING` | `false` |
   | `LLM_SLOT_GROUP` | `A` |
   | `DATABASE_URL` | `postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}` |
   | `QDRANT_URL`, `QDRANT_API_KEY` | from step 1 |
   | `SECRET_KEY` | a long random string (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`) |
   | `ADMIN_TOKEN` | a random string; `/api/admin/stats` then needs `X-Admin-Token` |
   | `UPLOAD_DIR` | `/data/uploads` |
   | `OFFLINE_DEMO_MODE` | `auto` |

   Leave `SESSION_COOKIE_SAMESITE=lax` and `CORS_ORIGINS` at their defaults: the browser only
   ever talks to the Vercel domain.
5. **Settings → Networking → Generate domain.** Check `https://<domain>/api/health` →
   `"status": "ok"`, `"app_env": "production"`. Outside our slot, `/api/system/status` shows
   `"offline_demo_mode": true`, which is expected.

## 3. Vercel
1. New project → this repo → **Root directory** `frontend` (framework: Vite). Keep "Include files
   outside the root directory" on: the theme reads `../design/tokens.json`.
2. In `frontend/vercel.json`, replace `REPLACE-WITH-RAILWAY-DOMAIN` with the Railway domain and
   commit.
3. Environment variable `VITE_API_URL` = empty string (the client then calls `/api/...` on the
   same origin, and the rewrite forwards it to Railway).
4. Deploy, open the site, sign up, and check that the cookie is set on the Vercel domain.

If uploads of several MB fail through the rewrite, point the frontend straight at Railway:
`VITE_API_URL=https://<railway domain>`, and on Railway set `SESSION_COOKIE_SAMESITE=none`,
`SESSION_COOKIE_SECURE=true`, `CORS_ORIGINS=https://<vercel domain>`.

## 4. Seed and warm up (in our slot)
Offline demo mode serves only results the platform already produced, so fill the class cache
while the key is live (`python3 scripts/slot.py`):
1. Railway service → **Shell**: `uv run python -m app.seed` (the demo world `OLIVE-7Q2`; the
   worker indexes the files and writes the class quiz sets).
2. When indexing is done, run `uv run python -m app.seed` again (the Class Wisdom tip).
3. In the browser, as a demo student in EN and in AR: placement for both courses, one Study
   Studio pack and one Audio episode per course, one Tutor session, and one Teach-Back answer.
4. `/api/admin/stats` (with `X-Admin-Token`) → note the compact/mid split, cache hits and
   repeated identical requests (should be 0) for the report.

## 5. After each deploy
`/api/health` ok · sign up · join `OLIVE-7Q2` · in-slot: a quiz runs (its calls show
`provider=cloud` in `/api/admin/stats`) · outside the slot: the banner shows, cached material
opens, and AI start buttons are disabled.
