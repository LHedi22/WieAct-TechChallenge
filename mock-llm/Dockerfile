# M0 stub image; M1 turns mock-llm into a uv project with the full fake platform.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/
RUN uv pip install --system --no-cache "fastapi>=0.162" "uvicorn>=0.54"
WORKDIR /app
COPY app.py .
EXPOSE 9000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9000"]
