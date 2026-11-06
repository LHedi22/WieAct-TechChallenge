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
# Watchdog (audit F-DOS-1): a worker that is alive but frozen stops heartbeating; after ~3 min of
# failed strict health checks (and a 2-minute grace at start) the container exits and the platform
# restarts it. Stale `running` jobs are recovered by the worker on its way back up.
health="http://127.0.0.1:${PORT:-8000}/api/health?strict=1"
probe() { python -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=10)" "$health" 2>/dev/null; }
started=$(date +%s); misses=0; last=0
while kill -0 "$worker" 2>/dev/null && kill -0 "$api" 2>/dev/null; do
  sleep 5
  now=$(date +%s)
  if [ $((now - started)) -ge 120 ] && [ $((now - last)) -ge 30 ]; then
    last=$now
    if probe; then misses=0; else misses=$((misses + 1)); fi
    if [ "$misses" -ge 6 ]; then
      echo "worker heartbeat missing for ~3 min; stopping the container" >&2
      break
    fi
  fi
done
echo "a process exited or stopped answering; stopping the container" >&2
kill "$worker" "$api" 2>/dev/null || true
exit 1
