"""Alembic migration — worker_runs table.

Composite PK on ``(name, key)`` is the lynchpin: it gives the UNIQUE
constraint the ``INSERT ... ON CONFLICT DO NOTHING RETURNING 1``
pattern relies on. No surrogate id; no need for one.

Revision ID: 0107_worker_runs
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0107_worker_runs"
down_revision = "0106_<previous>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_runs",
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column(
            "ran_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("name", "key", name="worker_runs_pkey"),
    )
    # Lookup pattern in the admin dashboard is "what runs has
    # 'leaderboard_close' done lately?" — covered by this index without
    # bloating the PK.
    op.create_index(
        "ix_worker_runs_name_ran_at",
        "worker_runs",
        ["name", sa.text("ran_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_worker_runs_name_ran_at", table_name="worker_runs")
    op.drop_table("worker_runs")
