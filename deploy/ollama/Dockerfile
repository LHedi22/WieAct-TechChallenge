# Railway service "ollama": our self-hosted embeddings (bge-m3, 1024 dims) for EMBED_PROVIDER=local.
# Chat never runs here; it stays on the EdNova platform. Declared service (DECISIONS.md).
FROM ollama/ollama:0.40.13
# Listen on every interface so the app reaches it over Railway's private network.
ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_KEEP_ALIVE=-1 \
    OLLAMA_NUM_PARALLEL=2 \
    EMBED_MODEL=bge-m3
COPY start.sh /start.sh
EXPOSE 11434
ENTRYPOINT ["/bin/sh", "/start.sh"]
