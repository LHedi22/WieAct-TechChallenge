"""Coin hooks around a job's life: reserve when created, commit on success, refund on failure or
cancel (docs/ECONOMY.md). Each hook runs in the caller's transaction, so a reservation is saved
with its job and a refund with the job's final status."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.wallet.service import LedgerCoins
from app.models import Job


class CoinHooks(Protocol):
    async def reserve(self, s: AsyncSession, job: Job) -> None: ...
    async def commit(self, s: AsyncSession, job: Job) -> None: ...
    async def refund(self, s: AsyncSession, job: Job) -> None: ...


coins: CoinHooks = LedgerCoins()
