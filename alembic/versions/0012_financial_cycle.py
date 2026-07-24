"""track the current salary-based financial cycle

Revision ID: 0012_financial_cycle
Revises: 0011_installment_schedule
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_financial_cycle"
down_revision: str | None = "0011_installment_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "financial_cycle_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "financial_cycle_started_at")
