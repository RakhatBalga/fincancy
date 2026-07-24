"""Tests for AnalyticsService aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, TransactionType, User
from app.repositories.category_repo import CategoryRepository
from app.services.analytics_service import AnalyticsService


async def _add_tx(
    session: AsyncSession,
    user: User,
    category_name: str,
    amount: float,
    when: datetime,
    tx_type: TransactionType = TransactionType.expense,
) -> None:
    category = await CategoryRepository(session).get_by_name(user.id, category_name)
    assert category is not None
    session.add(
        Transaction(
            user_id=user.id,
            category_id=category.id,
            amount=amount,
            type=tx_type,
            description=None,
            created_at=when,
        )
    )
    await session.commit()


async def test_period_report_totals_and_percentages(
    session: AsyncSession, user: User
) -> None:
    base = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    await _add_tx(session, user, "азық-түлік", 3000.0, base)
    await _add_tx(session, user, "азық-түлік", 1000.0, base + timedelta(hours=1))
    await _add_tx(session, user, "көлік", 1000.0, base + timedelta(hours=2))

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 1, tzinfo=timezone.utc)
    report = await AnalyticsService(session).period_report(
        user, "Июль", start, end
    )

    assert report.total == 5000.0
    # Ordered by total desc: Еда (4000, 80%) then Транспорт (1000, 20%).
    assert [r.name for r in report.rows] == ["азық-түлік", "көлік"]
    assert report.rows[0].total == 4000.0
    assert report.rows[0].percent == 80.0
    assert report.rows[1].percent == 20.0


async def test_period_report_excludes_income(
    session: AsyncSession, user: User
) -> None:
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    await _add_tx(session, user, "азық-түлік", 2000.0, base)
    await _add_tx(
        session, user, "басқа", 400000.0, base, TransactionType.income
    )

    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 1, tzinfo=timezone.utc)
    report = await AnalyticsService(session).period_report(
        user, "Июль", start, end
    )

    # Only the expense counts toward the spending report.
    assert report.total == 2000.0
    assert len(report.rows) == 1


async def test_period_report_empty(session: AsyncSession, user: User) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 31, tzinfo=timezone.utc)
    report = await AnalyticsService(session).period_report(
        user, "Пусто", start, end
    )
    assert report.total == 0.0
    assert report.rows == []


async def test_month_report_uses_financial_cycle_start(
    session: AsyncSession, user: User
) -> None:
    now = datetime.now(timezone.utc)
    user.financial_cycle_started_at = now - timedelta(days=1)
    await session.commit()
    await _add_tx(session, user, "азық-түлік", 9000.0, now - timedelta(days=2))
    await _add_tx(session, user, "азық-түлік", 2600.0, now)

    report = await AnalyticsService(session).month(user)

    assert report.total == 2600.0


async def test_weekly_digest_change_percent(
    session: AsyncSession, user: User
) -> None:
    from app.services import periods

    cur_start, _ = periods.week_range()
    prev_start, _ = periods.previous_week_range()

    # 1000 this week vs 500 last week -> +100%.
    await _add_tx(session, user, "азық-түлік", 1000.0, cur_start + timedelta(hours=1))
    await _add_tx(session, user, "азық-түлік", 500.0, prev_start + timedelta(hours=1))

    digest = await AnalyticsService(session).weekly_digest(user)

    assert digest["current_total"] == 1000.0
    assert digest["previous_total"] == 500.0
    assert digest["change_percent"] == 100.0
