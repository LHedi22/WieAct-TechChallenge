#!/bin/sh
# Start Ollama, pull the embeddings model once (kept on the volume at /root/.ollama), keep serving.
set -e
ollama serve &
server=$!
until ollama list >/dev/null 2>&1; do sleep 1; done
ollama pull "$EMBED_MODEL"
echo "ollama ready with $EMBED_MODEL"
wait "$server"
