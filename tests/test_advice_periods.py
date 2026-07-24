"""Tests for period-scoped AI financial summaries."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import advice_period_keyboard
from app.db.models import Transaction, TransactionType, User
from app.repositories.category_repo import CategoryRepository
from app.services import periods
from app.services.advisor_service import AdvicePeriod, AdvisorService


async def test_advice_summary_respects_selected_period(
    session: AsyncSession, user: User
) -> None:
    category = await CategoryRepository(session).get_by_name(user.id, "азық-түлік")
    assert category is not None
    now = periods.now()
    session.add_all(
        [
            Transaction(
                user_id=user.id,
                category_id=category.id,
                amount=2600,
                type=TransactionType.expense,
                description="сегодня",
                created_at=now,
            ),
            Transaction(
                user_id=user.id,
                category_id=category.id,
                amount=9000,
                type=TransactionType.expense,
                description="раньше",
                created_at=now - timedelta(days=40),
            ),
        ]
    )
    await session.commit()
    advisor = AdvisorService(session)

    today = await advisor._build_summary(user, period=AdvicePeriod.today)
    overall = await advisor._build_summary(user, period=AdvicePeriod.overall)

    assert today is not None and "Расходы за выбранный период: 2600 ₸" in today
    assert "11600 ₸" not in today
    assert overall is not None and "Расходы за выбранный период: 11600 ₸" in overall


def test_advice_period_keyboard_contains_all_scopes() -> None:
    keyboard = advice_period_keyboard()
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert callbacks == {
        "advice:today",
        "advice:week",
        "advice:month",
        "advice:overall",
    }
