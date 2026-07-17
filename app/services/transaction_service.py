"""Use-case service for recording transactions."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction, TransactionType
from app.repositories.budget_repo import BudgetRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.transaction_repo import TransactionRepository
from app.services.schemas import ParsedTransaction

log = structlog.get_logger(__name__)


class TransactionService:
    """Turns parsed input into persisted transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)
        self._categories = CategoryRepository(session)
        self._budgets = BudgetRepository(session)

    async def add_from_parsed(
        self, user_id: int, parsed: ParsedTransaction
    ) -> Transaction:
        """Persist a transaction described by a :class:`ParsedTransaction`.

        The category is matched by name (or created on the fly for a custom
        category name). Commits the surrounding transaction.
        """
        category = await self._categories.get_or_create(user_id, parsed.category)
        transaction = await self._transactions.create(
            user_id=user_id,
            category_id=category.id,
            amount=parsed.amount,
            tx_type=parsed.type,
            description=parsed.description,
        )
        await self._session.commit()
        log.info(
            "transaction_saved",
            user_id=user_id,
            transaction_id=transaction.id,
            category=category.name,
            amount=parsed.amount,
        )
        return transaction

    async def change_category(
        self, user_id: int, transaction_id: int, category_id: int
    ) -> Transaction | None:
        """Reassign a transaction to a different (owned) category.

        Returns the updated transaction, or ``None`` if the transaction or
        category does not belong to the user.
        """
        transaction = await self._session.get(Transaction, transaction_id)
        if transaction is None or transaction.user_id != user_id:
            return None
        category = await self._categories.get_by_id(category_id, user_id)
        if category is None:
            return None
        transaction.category_id = category.id
        await self._session.commit()
        log.info(
            "transaction_recategorized",
            user_id=user_id,
            transaction_id=transaction_id,
            category=category.name,
        )
        return transaction

    async def add(
        self,
        user_id: int,
        category_id: int,
        amount: float,
        tx_type: TransactionType,
        description: str | None = None,
    ) -> Transaction:
        """Low-level insert used by tests and internal callers."""
        transaction = await self._transactions.create(
            user_id=user_id,
            category_id=category_id,
            amount=amount,
            tx_type=tx_type,
            description=description,
        )
        await self._session.commit()
        return transaction

    async def _owned(self, user_id: int, transaction_id: int) -> Transaction | None:
        """Fetch a transaction only if it belongs to the user."""
        transaction = await self._session.get(Transaction, transaction_id)
        if transaction is None or transaction.user_id != user_id:
            return None
        return transaction

    async def update_amount(
        self, user_id: int, transaction_id: int, amount: float
    ) -> Transaction | None:
        """Change the amount of an owned transaction."""
        if amount <= 0:
            return None
        transaction = await self._owned(user_id, transaction_id)
        if transaction is None:
            return None
        transaction.amount = amount
        await self._session.commit()
        log.info(
            "transaction_amount_updated",
            user_id=user_id,
            transaction_id=transaction_id,
            amount=amount,
        )
        return transaction

    async def delete(self, user_id: int, transaction_id: int) -> bool:
        """Delete an owned transaction. Returns ``True`` if deleted."""
        transaction = await self._owned(user_id, transaction_id)
        if transaction is None:
            return False
        await self._session.delete(transaction)
        await self._session.commit()
        log.info(
            "transaction_deleted",
            user_id=user_id,
            transaction_id=transaction_id,
        )
        return True

    async def reset_all(self, user_id: int) -> tuple[int, int]:
        """Delete ALL transactions and budgets for this user only.

        Keeps the user profile, income, onboarding answers, and categories
        intact — only the financial history is wiped. Returns
        ``(transactions_deleted, budgets_deleted)``.
        """
        tx_count = await self._transactions.delete_all_for_user(user_id)
        budget_count = await self._budgets.delete_all_for_user(user_id)
        await self._session.commit()
        log.info(
            "user_data_reset",
            user_id=user_id,
            transactions_deleted=tx_count,
            budgets_deleted=budget_count,
        )
        return tx_count, budget_count
