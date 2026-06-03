"""CLI entrypoint for scheduled jobs.

Run via ``python -m myapp.jobs <job_name> [--now ISO8601]``.

Dual-purpose target:

* Manual operator (``make ecs-exec`` then ``python -m myapp.jobs
  leaderboard_close``) when CloudWatch surfaces a failed run.
* AWS EventBridge Scheduler → ECS RunTask (see 05-eventbridge/).

Each job is idempotent via ``claim_run``, so a retry from EventBridge
or a manual rerun on top of a successful slot is a safe no-op.

Exit codes:
* 0 — success (or slot already taken → no-op)
* 1 — unknown job name (argparse rejected the argument)
* 2 — job raised
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import Callable, Coroutine
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from myapp.db.session import AsyncSessionLocal
from myapp.jobs import leaderboard_close, squad_health, weekly_digest

logger = logging.getLogger("myapp.jobs")

MX_TZ = ZoneInfo("America/Mexico_City")

JobFn = Callable[[AsyncSession, datetime], Coroutine[None, None, None]]

# Keep alphabetical so the CDK EventBridge schedules can mirror this
# list verbatim.
JOBS: dict[str, JobFn] = {
    "leaderboard_close": leaderboard_close.run,
    "squad_health": squad_health.run,
    "weekly_digest": weekly_digest.run,
}


async def _run(job_name: str, now_iso: str | None) -> None:
    fn = JOBS[job_name]
    now_mx = (
        datetime.fromisoformat(now_iso).astimezone(MX_TZ)
        if now_iso
        else datetime.now(MX_TZ)
    )
    logger.info("job_start name=%s slot=%s", job_name, now_mx.isoformat())
    async with AsyncSessionLocal() as db:
        try:
            await fn(db, now_mx)
            await db.commit()
            logger.info("job_done name=%s", job_name)
        except Exception:
            await db.rollback()
            logger.exception("job_failed name=%s", job_name)
            raise


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="python -m myapp.jobs",
        description=(
            "Run a scheduled job exactly once for its (name, ISO-week) slot."
        ),
    )
    parser.add_argument("job", choices=sorted(JOBS), help="Job to run.")
    parser.add_argument(
        "--now",
        default=None,
        help="ISO 8601 timestamp override (for backfills / manual triggers).",
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args.job, args.now))
    except Exception:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
