#!/usr/bin/env bash
# PostToolUse: format the file Claude just wrote. Never fails the turn.
if command -v jq >/dev/null 2>&1; then
  path=$(jq -r '.tool_input.file_path // empty')
else  # no jq: same extraction with Python
  path=$("$(command -v python3 || command -v python)" -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path") or "")')
fi
path=${path//\\//}
[ -z "$path" ] || [ ! -f "$path" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
rel=${path#"${CLAUDE_PROJECT_DIR//\\//}"/}
# No uv / node_modules on the host (e.g. the macOS dev machine): format inside the running compose
# containers instead (backend/ is mounted at /app in "backend", frontend/ at /app in "frontend").
in_container() {  # service, command…
  docker compose ps --status running -q "$1" 2>/dev/null | grep -q . || return 1
  docker compose exec -T "$@" >/dev/null 2>&1
}
case "$path" in
  *.py)
    case "$rel" in backend/*) ;; *) exit 0;; esac
    if command -v uv >/dev/null 2>&1; then
      (cd backend && uv run --quiet ruff format "$path" >/dev/null 2>&1 && uv run --quiet ruff check --fix "$path" >/dev/null 2>&1) || true
    else
      in_container backend sh -c "uv run --quiet ruff format '${rel#backend/}' && uv run --quiet ruff check --fix '${rel#backend/}'" || true
    fi ;;
  *.ts|*.tsx|*.js|*.jsx|*.css|*.json|*.md)
    # prompts are model input: prettier would re-indent lines that follow a list
    case "$path" in */docs/*|*/.claude/*|*/app/prompts/*) exit 0;; esac
    case "$rel" in frontend/*) ;; *) exit 0;; esac
    if [ -x frontend/node_modules/.bin/prettier ]; then
      (cd frontend && pnpm exec prettier --write "$path" >/dev/null 2>&1) || true
    else
      in_container frontend pnpm exec prettier --write "${rel#frontend/}" || true
    fi ;;
esac
exit 0
