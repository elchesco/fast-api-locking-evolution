"""Attempt 1 — per-tick Postgres advisory lock.

Drop this into your worker module. The first replica to enter ``_tick``
acquires the lock and runs; later replicas exit immediately. The lock
is xact-scoped — it releases on the transaction's commit/rollback, so
the *next* 15-min tick competes from scratch.

What it fixes: concurrent replicas inside the same instant.
What it misses: sequential ticks across a longer slot (see post §
"Attempt 1: per-tick advisory lock").
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

MX_TZ = ZoneInfo("America/Mexico_City")

# Arbitrary 32-bit int, unique per worker. Postgres advisory locks
# don't enforce uniqueness across workers, so pick something
# distinctive (a 4-char ASCII hex tag works).
_TICK_LOCK_KEY = 0x4D424F54  # 'MBOT'


async def _try_tick_lock(db: AsyncSession) -> bool:
    """Non-blocking attempt — returns False if another session holds it."""
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)"),
        {"k": _TICK_LOCK_KEY},
    )
    return bool(result.scalar_one())


async def _tick() -> None:
    async with AsyncSessionLocal() as db:
        if not await _try_tick_lock(db):
            logger.debug("tick skipped — another replica holds the lock")
            return

        now_mx = datetime.now(MX_TZ)
        weekday, hour, minute = now_mx.weekday(), now_mx.hour, now_mx.minute

        # Wall-clock branches — each fires inside a 15-min slot.
        if weekday == 4 and hour == 18 and minute < 15:
            await _leaderboard_close(db, now_mx)

        await db.commit()  # releases the advisory lock


async def _leaderboard_close(db: AsyncSession, now_mx: datetime) -> None:
    # ... existing body — see 02-thread-sentinel/ for the next attempt
    ...
