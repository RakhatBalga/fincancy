"""Tests for human-friendly asset input formats."""

from app.bot.formatters import format_deposits, format_goal, format_goals
from app.bot.handlers.assets import _goal_input
from app.db.models import BrokerAccount, Deposit, FinancialGoal
from app.services.asset_service import WealthSummary


def test_simple_goal_input_defaults_to_zero_kzt() -> None:
    assert _goal_input("квартира 30000000") == (
        "квартира",
        30_000_000,
        0,
        "KZT",
    )


def test_simple_goal_input_accepts_spaced_amount() -> None:
    assert _goal_input("новая квартира 30 000 000 KZT") == (
        "новая квартира",
        30_000_000,
        0,
        "KZT",
    )


def test_detailed_goal_input_keeps_current_amount() -> None:
    assert _goal_input("MacBook | 1500000 | 300000 KZT") == (
        "MacBook",
        1_500_000,
        300_000,
        "KZT",
    )


def test_goal_formatter_shows_remaining_percent() -> None:
    goal = FinancialGoal(
        id=1,
        user_id=1,
        title="Квартира",
        target_amount=30_000_000,
        current_amount=6_000_000,
        currency="KZT",
    )

    text = format_goal(goal)

    assert "20.0%" in text
    assert "Осталось: 24 000 000 ₸ (80.0%)" in text


def test_deposits_formatter_combines_items_and_total() -> None:
    items = [
        Deposit(id=1, user_id=1, name="Депозит 1", balance=64_800, currency="KZT"),
        Deposit(
            id=2,
            user_id=1,
            name="Депозит 2",
            balance=2_249_866,
            currency="KZT",
        ),
    ]

    text = format_deposits(items)

    assert "Всего: <b>2 314 666 ₸</b>" in text
    assert "Депозит 1</b> — 64 800 ₸" in text
    assert "Депозит 2</b> — 2 249 866 ₸" in text


def test_goals_formatter_uses_complete_net_worth() -> None:
    goal = FinancialGoal(
        id=1,
        user_id=1,
        title="Квартира",
        target_amount=10_000_000,
        current_amount=0,
        currency="KZT",
    )
    deposit = Deposit(id=1, user_id=1, name="Депозит", balance=500_000, currency="KZT")
    account = BrokerAccount(
        user_id=1, cash_usd=1_000, realized_pnl_usd=0, transaction_count=0
    )
    summary = WealthSummary([], [deposit], 500, account)

    text = format_goals([goal], summary)

    assert "Весь капитал: <b>1 000 000 ₸</b> · <b>$2,000.00</b>" in text
    assert "10.0%" in text
    assert "Осталось: 9 000 000 ₸ (90.0%)" in text
