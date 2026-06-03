"""Atomic slot claim for scheduled jobs.

The three-line SQL pattern that is the whole point of the post.

* ``INSERT ... ON CONFLICT DO NOTHING`` is atomic at the row level —
  two concurrent writes see exactly one win.
* ``RETURNING 1`` only emits a row when the INSERT actually inserted,
  so the caller learns "did I win?" without a second query.
* The row participates in the caller's transaction. Caller commits →
  claim persists with the work; caller rolls back → claim disappears
  with the work, next tick gets a clean retry.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def claim_run(db: AsyncSession, name: str, key: str) -> bool:
    """Reserve ``(name, key)`` inside the caller's transaction.

    Returns True if this caller owns the slot, False if another
    transaction already claimed it.
    """
    result = await db.execute(
        text(
            """
            INSERT INTO worker_runs (name, key)
            VALUES (:name, :key)
            ON CONFLICT (name, key) DO NOTHING
            RETURNING 1
            """
        ),
        {"name": name, "key": key},
    )
    return result.scalar_one_or_none() is not None
