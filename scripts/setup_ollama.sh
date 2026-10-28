#!/usr/bin/env bash
# Set up local models for dev (never used in production or the demo — docs/DECISIONS.md).
# Usage (repo root): bash scripts/setup_ollama.sh
# Checks the install, pulls the models named in .env (LOCAL_MODEL_COMPACT / LOCAL_MODEL_MID /
# LOCAL_EMBEDDING_MODEL, or the defaults), warms them up, then runs llm.py check.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"

command -v ollama >/dev/null || { echo "Ollama is not installed: https://ollama.com/download"; exit 1; }
echo "Recommended server env: OLLAMA_NUM_PARALLEL=2 OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_KEEP_ALIVE=30m"

compact="qwen3:1.7b" mid="qwen3:14b" embed="bge-m3"
if [ "$(uname)" = "Linux" ] && [ "$(awk '/MemTotal/ {print int($2/1048576)}' /proc/meminfo)" -lt 16 ]; then
  mid="qwen3:8b"
fi
if [ -f "$root/.env" ]; then  # only the LOCAL_* model lines are read
  while IFS='=' read -r k v; do
    case "$k" in
      LOCAL_MODEL_COMPACT) compact="$v" ;;
      LOCAL_MODEL_MID) mid="$v" ;;
      LOCAL_EMBEDDING_MODEL) embed="$v" ;;
    esac
  done < <(grep -E '^LOCAL_(MODEL_COMPACT|MODEL_MID|EMBEDDING_MODEL)=' "$root/.env" || true)
fi

curl -fsS -m 5 http://127.0.0.1:11434/api/tags >/dev/null \
  || { echo "Ollama is not answering on 127.0.0.1:11434 — start it (ollama serve) and rerun"; exit 1; }

for m in "$compact" "$mid" "$embed"; do echo "ollama pull $m"; ollama pull "$m"; done

for m in "$compact" "$mid"; do
  start=$(date +%s)
  curl -fsS -m 600 http://127.0.0.1:11434/api/generate \
    -d "{\"model\":\"$m\",\"prompt\":\"Say OK. /no_think\",\"stream\":false,\"keep_alive\":\"30m\"}" >/dev/null
  echo "warmed $m in $(( $(date +%s) - start )) s"
done

python3 "$root/scripts/llm.py" check --provider local
