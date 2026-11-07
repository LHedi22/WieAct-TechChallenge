"""Live economy overrides: admin-set numbers merged over app/core/economy.py.

`effective()` is the one merge function: defaults from economy.py, then the `economy_overrides`
rows on top. `apply()` writes the result into the economy module itself, so everything that
already reads `economy.COST[...]`, `economy.DAILY_FREE_COINS`, … (`/api/economy`, every price
endpoint, the wallet, rewards) sees the same numbers. The API refreshes them on each request and
the worker on each tick, at most every TTL_S seconds (separate processes, no restart).

Only numbers that exist in economy.py can be overridden, all whole and never negative. A job's
price is fixed when it is created (`jobs.cost` + its ledger rows), so a change never touches coins
already reserved by a running job.
"""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import economy
from app.models import EconomyOverride

log = logging.getLogger("economy")
TTL_S = 3.0

# dotted key → (module attribute, nested keys…), with the allowed range
_SCALARS = {
    "daily_free_coins": ("DAILY_FREE_COINS", 0, 1000),
    "daily_earn_cap": ("DAILY_EARN_CAP", 0, 1000),
    "exam_pass_daily_limit": ("EXAM_PASS_DAILY_LIMIT", 0, 1000),
    "peer_answer_threshold": ("PEER_ANSWER_THRESHOLD", 0, 100),
    "wisdom_threshold": ("WISDOM_THRESHOLD", 1, 100),
    "teachback_review_band": ("TEACHBACK_REVIEW_BAND", 0, 100),
}
_DICTS = {"cost": "COST", "earn": "EARN", "points": "POINTS", "cosmetics": "COSMETICS"}
_PRODUCTS = {
    "products.coin_pack.coins": ("coin_pack", "coins", 1, 10_000),
    "products.exam_pass.days": ("exam_pass", "days", 1, 365),
}
_DICT_MAX = 10_000

_ORIGINAL = {
    name: copy.deepcopy(getattr(economy, name))
    for name in (
        "DAILY_FREE_COINS",
        "DAILY_EARN_CAP",
        "EXAM_PASS_DAILY_LIMIT",
        "PEER_ANSWER_THRESHOLD",
        "WISDOM_THRESHOLD",
        "TEACHBACK_REVIEW_BAND",
        "COST",
        "EARN",
        "POINTS",
        "COSMETICS",
        "PRODUCTS",
    )
}
_cache: tuple[float, dict[str, int]] | None = None


def defaults() -> dict[str, int]:
    out: dict[str, int] = {}
    for key, (attr, _, _) in _SCALARS.items():
        out[key] = _ORIGINAL[attr]
    for prefix, attr in _DICTS.items():
        for name, value in _ORIGINAL[attr].items():
            out[f"{prefix}.{name}"] = value
    for key, (product, field, _, _) in _PRODUCTS.items():
        out[key] = _ORIGINAL["PRODUCTS"][product][field]
    return out


def bounds(key: str) -> tuple[int, int]:
    if key in _SCALARS:
        return _SCALARS[key][1], _SCALARS[key][2]
    if key in _PRODUCTS:
        return _PRODUCTS[key][2], _PRODUCTS[key][3]
    if key.split(".", 1)[0] in _DICTS and key in defaults():
        return 0, _DICT_MAX
    raise KeyError(key)


def validate(key: str, value: Any) -> int:
    """The value to store, or ValueError with a plain message."""
    if key not in defaults():
        raise ValueError(f"{key} is not a number in economy.py")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number")
    lo, hi = bounds(key)
    if not lo <= value <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return value


def effective(overrides: dict[str, int]) -> dict[str, int]:
    """Defaults from economy.py with the valid overrides on top (invalid rows are ignored)."""
    out = defaults()
    for key, value in overrides.items():
        try:
            out[key] = validate(key, value)
        except ValueError:
            log.warning("ignoring invalid economy override %s", key)
    return out


def apply(overrides: dict[str, int]) -> dict[str, int]:
    values = effective(overrides)
    for key, (attr, _, _) in _SCALARS.items():
        setattr(economy, attr, values[key])
    for prefix, attr in _DICTS.items():
        target = getattr(economy, attr)
        for name in list(target):
            target[name] = values[f"{prefix}.{name}"]
    for key, (product, field, _, _) in _PRODUCTS.items():
        economy.PRODUCTS[product][field] = values[key]
    # derived from COST in economy.py
    economy.BUILDINGS["quiz_hall"]["cost"] = economy.COST["quiz"]
    economy.BUILDINGS["socratic_tutor"]["cost"] = economy.COST["tutor_session"]
    economy.BUILDINGS["study_studio"]["cost"] = economy.COST["generate_shared_asset"]
    economy.BUILDINGS["audio_studio"]["cost"] = economy.COST["generate_shared_asset"]
    economy.BUILDINGS["teachback_arena"]["cost"] = economy.COST["peer_question"]
    return values


def reset() -> None:
    """Back to economy.py (tests)."""
    global _cache
    _cache = None
    apply({})


def invalidate() -> None:
    global _cache
    _cache = None


async def rows(s: AsyncSession) -> dict[str, EconomyOverride]:
    return {r.key: r for r in await s.scalars(select(EconomyOverride))}


async def refresh(sm: async_sessionmaker[AsyncSession], *, fresh: bool = False) -> None:
    global _cache
    now = time.monotonic()
    if not fresh and _cache is not None and now - _cache[0] < TTL_S:
        return
    try:
        async with sm() as s:
            overrides = {r.key: r.value for r in await s.scalars(select(EconomyOverride))}
    except Exception:  # keep the last known numbers rather than failing a request
        log.warning("could not read economy_overrides; keeping the last values", exc_info=True)
        _cache = (now, _cache[1] if _cache else {})
        return
    _cache = (now, overrides)
    apply(overrides)
