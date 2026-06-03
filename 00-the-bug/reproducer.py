"""Reproducer for the duplicate-cron bug.

Run two copies of this script against the same Postgres URL with N
seconds between them. Each "replica" simulates the worker's 15-min
tick, including the "did we already do this slot?" thread-title check
that *almost* works. The point is to show the failure mode that
attempts 1 + 2 in the post don't catch.

Usage (one shell each):

    pip install asyncpg
    export DATABASE_URL=postgresql://myapp:password@localhost:5432/mydb
    python reproducer.py replica-A
    sleep 60 && python reproducer.py replica-B
    sleep 60 && python reproducer.py replica-C

Expect: three notifications for the same user, one per replica.
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg


SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS threads (
    id SERIAL PRIMARY KEY,
    title TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def run_tick(replica: str) -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(SCHEMA)

        # Best-effort dedupe by thread title — the property attempts 1
        # and 2 in the post relied on.
        title = "Top 3 — 2026-W22"
        existing = await conn.fetchval(
            "SELECT id FROM threads WHERE title = $1", title
        )
        if existing:
            print(f"[{replica}] thread {existing} exists — skipping")
            return

        # Write the notification first (this is where the bug lives —
        # the side effect commits even if the sentinel never does).
        await conn.execute(
            "INSERT INTO notifications (user_id, body) "
            "VALUES ($1, $2)",
            "user-1",
            "🥉 ¡Quedaste en el top 3! +10 GDT",
        )
        print(f"[{replica}] notification inserted")

        # Now post the recap thread. Simulate the silent failure by
        # deliberately NOT writing — pretend the section was renamed
        # and bot_service.post_thread returned None.
        print(f"[{replica}] would post thread {title!r} — but section is missing")

        # No exception → outer code "commits" the notification. Next
        # replica sees no thread → re-fires.
    finally:
        await conn.close()


if __name__ == "__main__":
    replica = sys.argv[1] if len(sys.argv) > 1 else "?"
    asyncio.run(run_tick(replica))
