#!/bin/sh
# Production (Railway): one container runs the API and the single job worker, so both see the
# same uploads volume and there is exactly one limiter (2 in flight per key; backend/CLAUDE.md).
# If either process exits, the container exits and the platform restarts both.
set -e
uv run alembic upgrade head
uv run python -m app.worker &
worker=$!
uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' &
api=$!
trap 'kill $worker $api 2>/dev/null' TERM INT
while kill -0 "$worker" 2>/dev/null && kill -0 "$api" 2>/dev/null; do
  sleep 5
done
echo "a process exited; stopping the container" >&2
kill "$worker" "$api" 2>/dev/null || true
exit 1
