"""Worker after the jobs/ refactor — thin dispatcher.

Compared to 01-advisory-lock/scheduled_worker.py:

* No job bodies in the worker. Each scheduled job lives in
  ``myapp/jobs/<name>.py`` and is also invokable via the CLI in
  04-cli-entrypoint/__main__.py.
* Worker tick still owns the transaction boundary (so the claim row
  + the work still commit/rollback atomically when invoked from
  here).
* Advisory lock stays as first-line defence against concurrent
  replicas; ``claim_run`` inside each job is the per-slot guarantee.

This is the steady-state shape before phase 2 (EventBridge) lands.
After phase 2, the wall-clock branches go away too — EventBridge
calls the CLI directly.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.db.session import AsyncSessionLocal
from myapp.jobs import leaderboard_close, squad_health, weekly_digest
from myapp.workers._heartbeat import heartbeat_loop

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 15 * 60
MX_TZ = ZoneInfo("America/Mexico_City")
_TICK_LOCK_KEY = 0x4D424F54  # 'MBOT'


async def _try_tick_lock(db: AsyncSession) -> bool:
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)"),
        {"k": _TICK_LOCK_KEY},
    )
    return bool(result.scalar_one())


async def _tick() -> None:
    async with AsyncSessionLocal() as db:
        if not await _try_tick_lock(db):
            return

        now_mx = datetime.now(MX_TZ)
        weekday, hour, minute = now_mx.weekday(), now_mx.hour, now_mx.minute

        # Wall-clock branches — the claim row inside each job is the
        # real guarantee. These ifs just avoid touching the DB outside
        # the slot. Phase 2 removes these entirely (EventBridge owns
        # "when" instead).
        if weekday == 0 and hour == 9 and minute < 15:
            await weekly_digest.run(db, now_mx)
        if weekday == 4 and hour == 18 and minute < 15:
            await leaderboard_close.run(db, now_mx)
        if weekday == 6 and hour == 19 and minute < 15:
            await squad_health.run(db, now_mx)

        await db.commit()


async def run_worker() -> None:
    await heartbeat_loop(
        name="scheduled_worker",
        interval_seconds=_INTERVAL_SECONDS,
        tick=_tick,
    )
