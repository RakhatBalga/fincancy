"""Tests for portfolio, deposit, and goal calculations."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services.asset_service import AssetService
from app.services.market_data import MarketDataError, MarketQuote


class FakeMarket:
    async def usd_kzt(self) -> float:
        return 500.0

    async def quote(self, symbol: str) -> MarketQuote:
        if symbol == "MISSING":
            raise MarketDataError("missing")
        return MarketQuote(symbol, 120.0, "USD", symbol)


async def test_wealth_combines_stocks_and_deposits(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    await service.add_position(user.id, "aapl", 2, 100)
    await service.add_deposit(user.id, "Kaspi", 100_000, "KZT", 15)

    summary = await service.wealth(user.id)

    assert summary.portfolio_usd == pytest.approx(240)
    assert summary.deposits_kzt == pytest.approx(100_000)
    assert summary.total_kzt == pytest.approx(220_000)
    assert summary.total_usd == pytest.approx(440)
    assert summary.positions[0].profit_usd == pytest.approx(40)
    assert summary.positions[0].profit_percent == pytest.approx(20)


async def test_missing_quote_uses_cost_basis_without_losing_position(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    await service.add_position(user.id, "MISSING", 3, 50)

    summary = await service.wealth(user.id)

    assert summary.positions[0].current_price_usd is None
    assert summary.positions[0].value_usd == pytest.approx(150)


async def test_goal_can_be_updated_and_deleted(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    goal = await service.add_goal(user.id, "MacBook", 1_500_000, 300_000, "kzt")

    updated = await service.update_goal_amount(user.id, goal.id, 450_000)
    assert updated is not None
    assert float(updated.current_amount) == pytest.approx(450_000)

    assert await service.delete_goal(user.id, goal.id)
    assert await service.goals(user.id) == []


async def test_deposit_balance_can_be_updated(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    deposit = await service.add_deposit(user.id, "Kaspi", 100_000, "KZT")

    updated = await service.update_deposit_balance(user.id, deposit.id, 125_000)

    assert updated is not None
    assert float(updated.balance) == pytest.approx(125_000)


async def test_deposit_interest_compounds_monthly_and_only_once(
    session: AsyncSession,
    user: User,
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    deposit = await service.add_deposit(user.id, "Ата", 500_000, "KZT", 15)
    deposit.interest_started_on = date(2026, 1, 31)
    await session.commit()

    accrued = await service.accrue_deposit_interest(date(2026, 3, 31))
    repeated = await service.accrue_deposit_interest(date(2026, 3, 31))

    assert len(accrued) == 1
    assert accrued[0].months == 2
    assert accrued[0].interest == pytest.approx(12_578.13)
    assert accrued[0].new_balance == pytest.approx(512_578.13)
    assert repeated == []
    assert deposit.interest_months_accrued == 2


async def test_sales_update_quantity_cash_and_cumulative_pnl(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    await service.add_position(user.id, "AAPL", 10, 100)
    await service.set_broker_snapshot(
        user.id,
        cash_usd=0,
        realized_pnl_usd=1_003.31,
        transaction_count=207,
        reported_total_pnl_usd=-223.99,
        reported_total_pnl_percent=-4.67,
    )

    profitable = await service.sell_position(user.id, "AAPL", 4, 120)
    losing = await service.sell_position(user.id, "AAPL", 2, 80)
    positions = await service.positions(user.id)

    assert float(profitable.sale.realized_pnl_usd) == pytest.approx(80)
    assert float(losing.sale.realized_pnl_usd) == pytest.approx(-40)
    assert float(losing.account.realized_pnl_usd) == pytest.approx(1_043.31)
    assert float(losing.account.cash_usd) == pytest.approx(640)
    assert losing.account.transaction_count == 209
    assert losing.remaining_quantity == pytest.approx(4)
    assert len(positions) == 1
    assert float(positions[0].quantity) == pytest.approx(4)


async def test_sale_uses_fifo_for_multiple_purchase_lots(
    session: AsyncSession, user: User
) -> None:
    service = AssetService(session, FakeMarket())  # type: ignore[arg-type]
    await service.add_position(user.id, "AAPL", 5, 100)
    await service.add_position(user.id, "AAPL", 5, 200)

    result = await service.sell_position(user.id, "AAPL", 5, 150)
    positions = await service.positions(user.id)

    assert float(result.sale.average_buy_price_usd) == pytest.approx(100)
    assert float(result.sale.realized_pnl_usd) == pytest.approx(250)
    assert len(positions) == 1
    assert float(positions[0].average_price_usd) == pytest.approx(200)
