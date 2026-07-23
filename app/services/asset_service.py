"""Use cases and calculations for assets and financial goals."""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BrokerAccount,
    Deposit,
    FinancialGoal,
    InvestmentPosition,
    StockSale,
)
from app.repositories.asset_repo import AssetRepository
from app.services import periods
from app.services.market_data import MarketDataError, YahooFinanceService


SUPPORTED_CURRENCIES = {"KZT", "USD"}


@dataclass(frozen=True)
class PositionValue:
    position: InvestmentPosition
    current_price_usd: float | None
    cost_usd: float
    value_usd: float

    @property
    def profit_usd(self) -> float:
        return self.value_usd - self.cost_usd

    @property
    def profit_percent(self) -> float:
        return self.profit_usd / self.cost_usd * 100 if self.cost_usd else 0


@dataclass(frozen=True)
class WealthSummary:
    positions: list[PositionValue]
    deposits: list[Deposit]
    usd_kzt: float
    broker_account: BrokerAccount | None = None

    @property
    def portfolio_usd(self) -> float:
        return sum(item.value_usd for item in self.positions)

    @property
    def broker_cash_usd(self) -> float:
        return float(self.broker_account.cash_usd) if self.broker_account else 0

    @property
    def broker_total_usd(self) -> float:
        return self.portfolio_usd + self.broker_cash_usd

    @property
    def deposits_kzt(self) -> float:
        return sum(
            float(item.balance) * (self.usd_kzt if item.currency == "USD" else 1)
            for item in self.deposits
        )

    @property
    def total_kzt(self) -> float:
        return self.broker_total_usd * self.usd_kzt + self.deposits_kzt

    @property
    def total_usd(self) -> float:
        return self.total_kzt / self.usd_kzt


@dataclass(frozen=True)
class SaleResult:
    sale: StockSale
    account: BrokerAccount
    remaining_quantity: float


@dataclass(frozen=True)
class DepositInterestAccrual:
    deposit_id: int
    user_id: int
    name: str
    currency: str
    previous_balance: float
    interest: float
    new_balance: float
    months: int


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class AssetService:
    def __init__(
        self, session: AsyncSession, market: YahooFinanceService | None = None
    ) -> None:
        self._session = session
        self._repo = AssetRepository(session)
        self._market = market or YahooFinanceService()

    async def add_position(
        self, user_id: int, symbol: str, quantity: float, average_price_usd: float
    ) -> InvestmentPosition:
        normalized = symbol.strip().upper()
        if not normalized or quantity <= 0 or average_price_usd <= 0:
            raise ValueError("position values must be positive")
        item = await self._repo.add_position(
            user_id, normalized, quantity, average_price_usd
        )
        await self._session.commit()
        return item

    async def add_deposit(
        self,
        user_id: int,
        name: str,
        balance: float,
        currency: str,
        annual_rate: float | None = None,
    ) -> Deposit:
        normalized_currency = currency.upper()
        if (
            not name.strip()
            or balance <= 0
            or normalized_currency not in SUPPORTED_CURRENCIES
            or (annual_rate is not None and annual_rate < 0)
        ):
            raise ValueError("invalid deposit")
        item = await self._repo.add_deposit(
            user_id,
            name.strip(),
            balance,
            normalized_currency,
            annual_rate,
            periods.today(),
        )
        await self._session.commit()
        return item

    async def accrue_deposit_interest(
        self,
        as_of: date,
    ) -> list[DepositInterestAccrual]:
        """Compound every fully elapsed monthly period exactly once."""
        deposits = list(
            (
                await self._session.execute(
                    select(Deposit)
                    .where(
                        Deposit.annual_rate.is_not(None),
                        Deposit.annual_rate > 0,
                    )
                    .order_by(Deposit.id.asc())
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        accrued: list[DepositInterestAccrual] = []
        for item in deposits:
            completed = int(item.interest_months_accrued)
            due_months = 0
            while _add_months(
                item.interest_started_on,
                completed + due_months + 1,
            ) <= as_of:
                due_months += 1
            if due_months == 0:
                continue

            previous = Decimal(str(item.balance))
            monthly_rate = Decimal(str(item.annual_rate)) / Decimal("1200")
            updated = (
                previous * (Decimal("1") + monthly_rate) ** due_months
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            interest = updated - previous
            item.balance = updated
            item.interest_months_accrued = completed + due_months
            accrued.append(
                DepositInterestAccrual(
                    deposit_id=item.id,
                    user_id=item.user_id,
                    name=item.name,
                    currency=item.currency,
                    previous_balance=float(previous),
                    interest=float(interest),
                    new_balance=float(updated),
                    months=due_months,
                )
            )

        await self._session.commit()
        return accrued

    async def add_goal(
        self,
        user_id: int,
        title: str,
        target_amount: float,
        current_amount: float,
        currency: str,
    ) -> FinancialGoal:
        normalized_currency = currency.upper()
        if (
            not title.strip()
            or target_amount <= 0
            or current_amount < 0
            or normalized_currency not in SUPPORTED_CURRENCIES
        ):
            raise ValueError("invalid goal")
        item = await self._repo.add_goal(
            user_id,
            title.strip(),
            target_amount,
            current_amount,
            normalized_currency,
        )
        await self._session.commit()
        return item

    async def update_goal_amount(
        self, user_id: int, goal_id: int, current_amount: float
    ) -> FinancialGoal | None:
        if current_amount < 0:
            return None
        goal = await self._session.get(FinancialGoal, goal_id)
        if goal is None or goal.user_id != user_id:
            return None
        goal.current_amount = current_amount
        await self._session.commit()
        return goal

    async def update_deposit_balance(
        self, user_id: int, deposit_id: int, balance: float
    ) -> Deposit | None:
        if balance < 0:
            return None
        deposit = await self._session.get(Deposit, deposit_id)
        if deposit is None or deposit.user_id != user_id:
            return None
        deposit.balance = balance
        await self._session.commit()
        return deposit

    async def positions(self, user_id: int) -> list[InvestmentPosition]:
        return await self._repo.list_positions(user_id)

    async def deposits(self, user_id: int) -> list[Deposit]:
        return await self._repo.list_deposits(user_id)

    async def goals(self, user_id: int) -> list[FinancialGoal]:
        return await self._repo.list_goals(user_id)

    async def broker_account(self, user_id: int) -> BrokerAccount | None:
        return await self._session.scalar(
            select(BrokerAccount).where(BrokerAccount.user_id == user_id)
        )

    async def set_broker_snapshot(
        self,
        user_id: int,
        *,
        cash_usd: float,
        realized_pnl_usd: float,
        transaction_count: int,
        reported_total_pnl_usd: float | None = None,
        reported_total_pnl_percent: float | None = None,
    ) -> BrokerAccount:
        account = await self.broker_account(user_id)
        if account is None:
            account = BrokerAccount(user_id=user_id)
            self._session.add(account)
        account.cash_usd = cash_usd
        account.realized_pnl_usd = realized_pnl_usd
        account.transaction_count = transaction_count
        account.reported_total_pnl_usd = reported_total_pnl_usd
        account.reported_total_pnl_percent = reported_total_pnl_percent
        await self._session.commit()
        return account

    async def sell_position(
        self, user_id: int, symbol: str, quantity: float, sell_price_usd: float
    ) -> SaleResult:
        normalized = symbol.strip().upper()
        if not normalized or quantity <= 0 or sell_price_usd <= 0:
            raise ValueError("sale values must be positive")

        positions = list(
            (
                await self._session.execute(
                    select(InvestmentPosition)
                    .where(
                        InvestmentPosition.user_id == user_id,
                        InvestmentPosition.symbol == normalized,
                    )
                    .order_by(
                        InvestmentPosition.created_at.asc(),
                        InvestmentPosition.id.asc(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        available = sum(float(item.quantity) for item in positions)
        if available + 1e-9 < quantity:
            raise ValueError(f"only {available:g} shares available")

        remaining_to_sell = quantity
        sold_cost = 0.0
        for position in positions:
            owned = float(position.quantity)
            sold = min(owned, remaining_to_sell)
            sold_cost += sold * float(position.average_price_usd)
            new_quantity = owned - sold
            if new_quantity <= 1e-9:
                await self._session.delete(position)
            else:
                position.quantity = new_quantity
            remaining_to_sell -= sold
            if remaining_to_sell <= 1e-9:
                break

        average_buy_price = sold_cost / quantity
        realized_pnl = quantity * (sell_price_usd - average_buy_price)

        account = await self._session.scalar(
            select(BrokerAccount)
            .where(BrokerAccount.user_id == user_id)
            .with_for_update()
        )
        if account is None:
            account = BrokerAccount(user_id=user_id)
            self._session.add(account)
        account.cash_usd = float(account.cash_usd or 0) + quantity * sell_price_usd
        account.realized_pnl_usd = float(account.realized_pnl_usd or 0) + realized_pnl
        account.transaction_count = int(account.transaction_count or 0) + 1

        sale = StockSale(
            user_id=user_id,
            symbol=normalized,
            quantity=quantity,
            average_buy_price_usd=average_buy_price,
            sell_price_usd=sell_price_usd,
            realized_pnl_usd=realized_pnl,
        )
        self._session.add(sale)
        await self._session.commit()
        return SaleResult(sale, account, available - quantity)

    async def wealth(self, user_id: int) -> WealthSummary:
        positions = await self.positions(user_id)
        deposits = await self.deposits(user_id)
        account = await self.broker_account(user_id)
        usd_kzt = await self._market.usd_kzt()

        async def value_position(position: InvestmentPosition) -> PositionValue:
            cost = float(position.quantity) * float(position.average_price_usd)
            try:
                quote = await self._market.quote(position.symbol)
                if quote.currency != "USD":
                    raise MarketDataError("only USD stock quotes are supported")
                current_price = quote.price
                value = float(position.quantity) * current_price
            except MarketDataError:
                current_price = None
                value = cost
            return PositionValue(position, current_price, cost, value)

        values = list(
            await asyncio.gather(*(value_position(item) for item in positions))
        )
        return WealthSummary(values, deposits, usd_kzt, account)

    async def delete_position(self, user_id: int, item_id: int) -> bool:
        return await self._repo.delete_owned(InvestmentPosition, user_id, item_id)

    async def delete_deposit(self, user_id: int, item_id: int) -> bool:
        return await self._repo.delete_owned(Deposit, user_id, item_id)

    async def delete_goal(self, user_id: int, item_id: int) -> bool:
        return await self._repo.delete_owned(FinancialGoal, user_id, item_id)
