"""Job worker entry point: `python -m app.worker`. One process — the gateway's limiter (2 in
flight, RPM) is process-local, so there must be exactly one worker (backend/CLAUDE.md)."""

import asyncio
import logging

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.jobs.worker import Worker

log = logging.getLogger("worker")


async def main() -> None:
    settings = get_settings()
    log.info(
        "worker started (provider=%s, app_env=%s, max %d in flight, %d rpm)",
        settings.LLM_PROVIDER,
        settings.APP_ENV,
        settings.LLM_MAX_CONCURRENCY,
        settings.LLM_MAX_RPM,
    )
    await Worker(get_sessionmaker(), background_slots=settings.LLM_MAX_CONCURRENCY).run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
