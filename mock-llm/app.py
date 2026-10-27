"""M0 stub so docker compose has a mock-llm service. The real fake platform is built in M1
(see README.md)."""

from fastapi import FastAPI

app = FastAPI(title="mock-llm (stub)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "stub", "note": "mock-llm is implemented in M1"}
