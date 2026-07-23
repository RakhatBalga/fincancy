"""Data access for investments, deposits, and financial goals."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Deposit, FinancialGoal, InvestmentPosition


class AssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_position(
        self, user_id: int, symbol: str, quantity: float, average_price_usd: float
    ) -> InvestmentPosition:
        item = InvestmentPosition(
            user_id=user_id,
            symbol=symbol,
            quantity=quantity,
            average_price_usd=average_price_usd,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def list_positions(self, user_id: int) -> list[InvestmentPosition]:
        result = await self._session.execute(
            select(InvestmentPosition)
            .where(InvestmentPosition.user_id == user_id)
            .order_by(InvestmentPosition.created_at.asc(), InvestmentPosition.id.asc())
        )
        return list(result.scalars().all())

    async def add_deposit(
        self,
        user_id: int,
        name: str,
        balance: float,
        currency: str,
        annual_rate: float | None,
        interest_started_on: date,
    ) -> Deposit:
        item = Deposit(
            user_id=user_id,
            name=name,
            balance=balance,
            currency=currency,
            annual_rate=annual_rate,
            interest_started_on=interest_started_on,
            interest_months_accrued=0,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def list_deposits(self, user_id: int) -> list[Deposit]:
        result = await self._session.execute(
            select(Deposit)
            .where(Deposit.user_id == user_id)
            .order_by(Deposit.created_at.asc(), Deposit.id.asc())
        )
        return list(result.scalars().all())

    async def add_goal(
        self,
        user_id: int,
        title: str,
        target_amount: float,
        current_amount: float,
        currency: str,
    ) -> FinancialGoal:
        item = FinancialGoal(
            user_id=user_id,
            title=title,
            target_amount=target_amount,
            current_amount=current_amount,
            currency=currency,
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def list_goals(self, user_id: int) -> list[FinancialGoal]:
        result = await self._session.execute(
            select(FinancialGoal)
            .where(FinancialGoal.user_id == user_id)
            .order_by(FinancialGoal.created_at.asc(), FinancialGoal.id.asc())
        )
        return list(result.scalars().all())

    async def delete_owned(self, model: type, user_id: int, item_id: int) -> bool:
        item = await self._session.get(model, item_id)
        if item is None or item.user_id != user_id:
            return False
        await self._session.delete(item)
        await self._session.commit()
        return True
