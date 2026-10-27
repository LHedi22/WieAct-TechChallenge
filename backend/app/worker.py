"""Job worker (python -m app.worker).

M0 stub: validates settings and idles with a heartbeat so docker compose has a running worker.
The real loop (SELECT … FOR UPDATE SKIP LOCKED, lanes, not_before) arrives in M1.
"""

import asyncio
import logging

from app.core.config import get_settings

log = logging.getLogger("worker")

HEARTBEAT_S = 60


async def main() -> None:
    settings = get_settings()
    log.info("worker started (provider=%s, app_env=%s)", settings.llm.provider, settings.APP_ENV)
    while True:
        log.info("worker idle: job runner arrives in M1")
        await asyncio.sleep(HEARTBEAT_S)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
