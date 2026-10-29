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
case "$path" in
  *.py)
    (cd backend 2>/dev/null && uv run --quiet ruff format "$path" >/dev/null 2>&1 && uv run --quiet ruff check --fix "$path" >/dev/null 2>&1) || true ;;
  *.ts|*.tsx|*.js|*.jsx|*.css|*.json|*.md)
    # prompts are model input: prettier would re-indent lines that follow a list
    case "$path" in */docs/*|*/.claude/*|*/app/prompts/*) exit 0;; esac
    (cd frontend 2>/dev/null && pnpm exec prettier --write "$path" >/dev/null 2>&1) || true ;;
esac
exit 0
