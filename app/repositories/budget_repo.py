"""Data access for :class:`Budget`."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Budget


class BudgetRepository:
    """CRUD operations for monthly per-category budgets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, user_id: int, category_id: int, monthly_limit: float, month: str
    ) -> None:
        """Insert or update the limit for ``(user, category, month)``.

        Uses PostgreSQL ``ON CONFLICT`` so re-running ``/setbudget`` overwrites
        the previous limit instead of erroring on the unique constraint.
        """
        stmt = pg_insert(Budget).values(
            user_id=user_id,
            category_id=category_id,
            monthly_limit=monthly_limit,
            month=month,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_budget_user_category_month",
            set_={"monthly_limit": monthly_limit},
        )
        await self._session.execute(stmt)

    async def list_for_month(self, user_id: int, month: str) -> list[Budget]:
        result = await self._session.execute(
            select(Budget).where(Budget.user_id == user_id, Budget.month == month)
        )
        return list(result.scalars().all())

    async def delete_all_for_user(self, user_id: int) -> int:
        """Delete every budget belonging to ``user_id``. Returns count deleted."""
        result = await self._session.execute(
            delete(Budget).where(Budget.user_id == user_id)
        )
        return result.rowcount or 0
