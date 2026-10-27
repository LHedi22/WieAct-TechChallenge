#!/usr/bin/env bash
# PreToolUse guard: blocks edits that would leak the API key, hard-code the platform URL,
# or call the LLM from outside backend/app/gateway/. Exit 2 = block, stderr goes to Claude.
input=$(cat)
if command -v jq >/dev/null 2>&1; then
  path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
  text=$(printf '%s' "$input" | jq -r '[.tool_input.content, .tool_input.new_string, (.tool_input.edits // [] | map(.new_string) | join("\n"))] | map(select(. != null)) | join("\n")')
else  # no jq (e.g. Windows without it): same extraction with Python
  py=$(command -v python3 || command -v python)
  path=$(printf '%s' "$input" | "$py" -c 'import json,sys; t=json.load(sys.stdin).get("tool_input",{}); print(t.get("file_path") or "")')
  text=$(printf '%s' "$input" | "$py" -c 'import json,sys; t=json.load(sys.stdin).get("tool_input",{}); print("\n".join(x for x in [t.get("content"), t.get("new_string"), "\n".join(e.get("new_string") or "" for e in t.get("edits") or [])] if x))')
fi
[ -z "$path" ] && exit 0
# Windows paths arrive with backslashes: normalise before taking the repo-relative path
path=${path//\\//}
rel=${path#"${CLAUDE_PROJECT_DIR//\\//}"/}

case "$rel" in
  .env|*/.env|.env.local|*.env.local) echo "Blocked: never write .env files. Edit .env.example instead." >&2; exit 2;;
esac

# 1. Platform URL only allowed in docs, .env.example and mock config
if printf '%s' "$text" | grep -qi 'felcloud\.io'; then
  case "$rel" in docs/*|.env.example|CLAUDE.md|README.md|.claude/*) ;; *)
    echo "Blocked: the platform base URL must come from settings.llm (CLOUD_BASE_URL in .env), never hard-coded in $rel." >&2; exit 2;;
  esac
fi

# 2. Anything that looks like a real API key
if printf '%s' "$text" | grep -Eq '(sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]{24,})'; then
  echo "Blocked: content looks like an API key or bearer token. Keys come from settings.llm (CLOUD_API_KEY in .env)." >&2; exit 2
fi

# 3. Direct LLM SDK use outside the gateway / mock / tests
if printf '%s' "$text" | grep -Eq '^\s*(from openai|import openai)|AsyncOpenAI\(|OpenAI\('; then
  case "$rel" in backend/app/gateway/*|mock-llm/*|backend/tests/*|docs/*|.claude/*|*.md) ;; *)
    echo "Blocked: only backend/app/gateway/ may use the OpenAI SDK. Call gateway.run(Task) from $rel." >&2; exit 2;;
  esac
fi

# 4. Frontend must never talk to the LLM
case "$rel" in frontend/*)
  if printf '%s' "$text" | grep -Eq '/v1/chat/completions|/v1/embeddings|(CLOUD|LOCAL|MOCK)_API_KEY|:11434'; then
    echo "Blocked: the frontend never calls the LLM. Go through /api/* and jobs." >&2; exit 2
  fi;;
esac
exit 0
