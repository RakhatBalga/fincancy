"""Tests for TransactionService."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TransactionType, User
from app.repositories.category_repo import CategoryRepository
from app.services.schemas import ParsedTransaction
from app.services.transaction_service import TransactionService


async def test_add_from_parsed_creates_transaction(
    session: AsyncSession, user: User
) -> None:
    parsed = ParsedTransaction(
        amount=800.0,
        category="азық-түлік",
        type=TransactionType.expense,
        description="кофе",
    )

    tx = await TransactionService(session).add_from_parsed(user.id, parsed)

    assert tx.id is not None
    assert float(tx.amount) == 800.0
    assert tx.type is TransactionType.expense
    # Matched an existing default category, did not create a duplicate.
    category = await CategoryRepository(session).get_by_id(tx.category_id, user.id)
    assert category is not None
    assert category.name == "азық-түлік"


async def test_add_from_parsed_creates_custom_category(
    session: AsyncSession, user: User
) -> None:
    parsed = ParsedTransaction(
        amount=5000.0,
        category="үй жануарлары",
        type=TransactionType.expense,
        description="корм",
    )

    tx = await TransactionService(session).add_from_parsed(user.id, parsed)

    category = await CategoryRepository(session).get_by_name(user.id, "үй жануарлары")
    assert category is not None
    assert category.is_default is False
    assert tx.category_id == category.id


async def test_official_income_starts_financial_cycle(
    session: AsyncSession, user: User
) -> None:
    parsed = ParsedTransaction(
        amount=121_000,
        category="жалақы",
        type=TransactionType.income,
        description="зарплата",
    )

    await TransactionService(session).add_from_parsed(user.id, parsed)

    assert user.financial_cycle_started_at is not None


async def test_change_category_reassigns(
    session: AsyncSession, user: User
) -> None:
    repo = CategoryRepository(session)
    service = TransactionService(session)

    parsed = ParsedTransaction(
        amount=1500.0,
        category="көлік",
        type=TransactionType.expense,
        description="такси",
    )
    tx = await service.add_from_parsed(user.id, parsed)
    target = await repo.get_by_name(user.id, "ойын-сауық")
    assert target is not None

    updated = await service.change_category(user.id, tx.id, target.id)

    assert updated is not None
    assert updated.category_id == target.id


async def test_change_category_rejects_foreign_transaction(
    session: AsyncSession, user: User
) -> None:
    service = TransactionService(session)
    result = await service.change_category(
        user_id=user.id, transaction_id=999, category_id=1
    )
    assert result is None
