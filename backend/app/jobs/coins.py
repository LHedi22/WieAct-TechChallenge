"""Coin hooks around a job's life: reserve when created, commit on success, refund on failure or
cancel (docs/ECONOMY.md). The wallet ledgers arrive in M5; until then the hooks are no-ops."""

from __future__ import annotations

from typing import Protocol

from app.models import Job


class CoinHooks(Protocol):
    async def reserve(self, job: Job) -> None: ...
    async def commit(self, job: Job) -> None: ...
    async def refund(self, job: Job) -> None: ...


class NoopCoins:
    async def reserve(self, job: Job) -> None:
        return None

    async def commit(self, job: Job) -> None:
        return None

    async def refund(self, job: Job) -> None:
        return None


coins: CoinHooks = NoopCoins()
