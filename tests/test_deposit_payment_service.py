"""Tests for compound deposit withdrawal and installment payment."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TransactionType, User
from app.repositories.transaction_repo import TransactionRepository
from app.services.asset_service import AssetService
from app.services.deposit_payment_service import (
    DepositPaymentError,
    DepositPaymentService,
    parse_deposit_payment,
)


def test_parse_deposit_payment_with_compact_amount() -> None:
    draft = parse_deposit_payment(
        "вывел 53к из Депозита 1 и оплатил рассрочку Kaspi"
    )

    assert draft is not None
    assert draft.amount == 53_000
    assert draft.deposit_name == "Депозита 1"
    assert draft.payment_label == "рассрочка Kaspi"


async def test_apply_withdraws_deposit_and_creates_expense(
    session: AsyncSession, user: User
) -> None:
    deposit = await AssetService(session).add_deposit(
        user.id, "Депозит 1", 135_800, "KZT"
    )
    draft = parse_deposit_payment(
        "снял 53 000 тенге с депозита 1 и погасил рассрочку Kaspi"
    )
    assert draft is not None

    result = await DepositPaymentService(session).apply(user.id, draft)
    rows = await TransactionRepository(session).list_recent(user.id, 1)

    assert float(result.deposit.balance) == 82_800
    assert rows[0].type is TransactionType.expense
    assert float(rows[0].amount) == 53_000
    assert rows[0].description == "рассрочка Kaspi"
    assert deposit.id == result.deposit.id


async def test_apply_rejects_insufficient_balance_without_changes(
    session: AsyncSession, user: User
) -> None:
    deposit = await AssetService(session).add_deposit(
        user.id, "Ата", 10_000, "KZT"
    )
    draft = parse_deposit_payment(
        "вывел 20к из депозита Ата и оплатил рассрочку Halyk"
    )
    assert draft is not None

    with pytest.raises(DepositPaymentError, match="Недостаточно"):
        await DepositPaymentService(session).apply(user.id, draft)

    assert float(deposit.balance) == 10_000
    assert await TransactionRepository(session).list_recent(user.id, 1) == []
