"""monthly deposit interest tracking

Revision ID: 0006_deposit_interest
Revises: 0005_broker_sales
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_deposit_interest"
down_revision: str | None = "0005_broker_sales"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deposits",
        sa.Column(
            "interest_started_on",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
    )
    op.add_column(
        "deposits",
        sa.Column(
            "interest_months_accrued",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("deposits", "interest_months_accrued")
    op.drop_column("deposits", "interest_started_on")
