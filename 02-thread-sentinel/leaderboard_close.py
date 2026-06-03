"""Attempt 2 — sentinel-by-existence inside the job.

Idempotency check: "if a thread with this week's recap title already
exists, skip." Works if and only if the side effect that creates the
thread succeeds. The trap: ``bot_service.post_thread`` returns None
silently when the section / bot user is missing, the sentinel never
lands, every later tick re-fires.

This is the file that produced the production incident in the post.
Kept here as documentation of the failure mode, not as a recommended
pattern.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myapp.models.forum import Thread
from myapp.models.notifications import Notification, NotificationType
from myapp.models.tokens import TokenAction, TokenTransaction
from myapp.models.user import User
from myapp.services import bot_service

_LEADERBOARD_PRIZES = {1: 50, 2: 20, 3: 10}


async def _leaderboard_close(db: AsyncSession, now_mx: datetime) -> None:
    title = f"🏆 Top 3 de la semana — {now_mx.strftime('%d %b %Y')}"
    # ↓ The dedupe everybody relies on. It's reading the result of a
    # ↓ side effect; if the side effect failed silently last time, this
    # ↓ check passes when it shouldn't.
    existing = (
        await db.execute(select(Thread).where(Thread.title == title).limit(1))
    ).scalar_one_or_none()
    if existing:
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

    # ↓ The silent-failure case. If section/bot is missing, this returns
    # ↓ None without raising. The Notifications + Transactions above are
    # ↓ still in the session and get committed by the caller. The Thread
    # ↓ sentinel never lands. Next tick reads "no thread for this week"
    # ↓ → re-fires the work → triple notification.
    await bot_service.post_thread(
        db,
        section_slug="general",
        title=title,
        body_md="...",
    )
