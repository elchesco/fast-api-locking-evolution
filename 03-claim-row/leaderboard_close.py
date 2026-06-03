"""Attempt 3 — the job uses ``claim_run`` as its first action.

Differences from attempt 2 (02-thread-sentinel/leaderboard_close.py):

* No SELECT-by-title check. The claim row is the sentinel.
* No commit inside the function — the caller owns it. This is what
  makes the "rollback releases the slot" property work: if anything
  raises after ``claim_run`` returns True, the caller's rollback
  takes the claim with it.
* ``post_thread`` returning None silently is still a bug, but it's
  no longer a *correctness* bug — it just means the recap thread is
  missing from the forum, which is visible and easy to spot. The
  GDT awards + notifications no longer get duplicated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.jobs._idempotency import claim_run
from myapp.models.notifications import Notification, NotificationType
from myapp.models.tokens import TokenAction, TokenTransaction
from myapp.models.user import User
from myapp.services import bot_service

_LEADERBOARD_PRIZES = {1: 50, 2: 20, 3: 10}


async def run(db: AsyncSession, now_mx: datetime) -> None:
    iso_year, iso_week, _ = now_mx.isocalendar()
    if not await claim_run(
        db, "leaderboard_close", f"{iso_year}-W{iso_week:02d}"
    ):
        return

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        await db.execute(
            select(
                TokenTransaction.user_id,
                func.sum(TokenTransaction.amount).label("earned"),
            )
            .where(
                TokenTransaction.created_at >= week_ago,
                TokenTransaction.amount > 0,
            )
            .group_by(TokenTransaction.user_id)
            .order_by(func.sum(TokenTransaction.amount).desc())
            .limit(3)
        )
    ).all()
    if not rows:
        return

    medals = ["🥇", "🥈", "🥉"]
    for idx, (user_id, earned) in enumerate(rows):
        prize = _LEADERBOARD_PRIZES.get(idx + 1, 0)
        user = await db.get(User, user_id)
        if user is None:
            continue
        user.gdt_balance = (user.gdt_balance or 0) + prize
        db.add(
            TokenTransaction(
                user_id=user.id,
                action=TokenAction.MANUAL_ADJUSTMENT,
                amount=prize,
                description=f"Bonus leaderboard #{idx + 1} ({now_mx.strftime('%Y-%W')})",
            )
        )
        db.add(
            Notification(
                user_id=user.id,
                type=NotificationType.LEADERBOARD_TOP3,
                title=f"{medals[idx]} ¡Quedaste en el top {idx + 1}!",
                body=f"+{prize} GDT por tu actividad esta semana.",
            )
        )

    await bot_service.post_thread(
        db,
        section_slug="general",
        title=f"🏆 Top 3 de la semana — {now_mx.strftime('%d %b %Y')}",
        body_md="...",
    )
    # No commit here. The caller's transaction wraps the whole thing
    # so the claim row + the work land atomically.
