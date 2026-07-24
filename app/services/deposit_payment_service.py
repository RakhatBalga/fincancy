"""Atomic deposit withdrawal followed by an installment payment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Deposit, Transaction, TransactionType
from app.repositories.asset_repo import AssetRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.transaction_repo import TransactionRepository

_AMOUNT = r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+(?:[.,]\d+)?)\s*(?:к|k|тыс\.?)?"
_PAYMENT_RE = re.compile(
    rf"""
    \b(?:вывел|вывела|снял|сняла|вытащил|вытащила)\s+
    (?P<amount>{_AMOUNT})\s*(?:₸|тг|тенге)?\s+
    (?:из|с|со)\s+(?P<deposit>.+?)\s+
    (?:и\s+)?
    (?:оплатил|оплатила|погасил|погасила|вн[её]с|внесла)\s+
    (?P<obligation>рассроч\w*|кредит\w*|плат[её]ж\w*)
    (?:\s+(?P<label>.+?))?
    [.!]?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_WITHDRAW_WORDS = ("вывел", "вывела", "снял", "сняла", "вытащил", "вытащила")
_PAYMENT_WORDS = ("оплатил", "оплатила", "погасил", "погасила", "внёс", "внес")
_DEPOSIT_PREFIX_RE = re.compile(r"^(?:из\s+|с\s+|со\s+)?(?:депозит[ае]?|вклад[ае]?)\s+")


class DepositPaymentError(ValueError):
    """The compound operation is invalid and must not be persisted."""


@dataclass(frozen=True)
class DepositPaymentDraft:
    amount: float
    deposit_name: str
    payment_label: str


@dataclass(frozen=True)
class DepositPaymentResult:
    deposit: Deposit
    transaction: Transaction
    previous_balance: float


def looks_like_deposit_payment(text: str) -> bool:
    lowered = text.casefold()
    return (
        any(word in lowered for word in _WITHDRAW_WORDS)
        and ("депозит" in lowered or "вклад" in lowered)
        and (
            any(word in lowered for word in _PAYMENT_WORDS)
            or "рассроч" in lowered
        )
    )


def _parse_amount(raw: str) -> float:
    normalized = raw.casefold().replace("\u00a0", " ").strip()
    multiplier = 1000 if re.search(r"(?:к|k|тыс\.?)$", normalized) else 1
    normalized = re.sub(r"\s*(?:к|k|тыс\.?)$", "", normalized)
    normalized = normalized.replace(" ", "").replace(",", ".")
    return float(normalized) * multiplier


def parse_deposit_payment(text: str) -> DepositPaymentDraft | None:
    match = _PAYMENT_RE.search(text.strip())
    if match is None:
        return None
    amount = _parse_amount(match.group("amount"))
    label = (match.group("label") or "").strip(" .")
    payment_label = "рассрочка" + (f" {label}" if label else "")
    return DepositPaymentDraft(
        amount=amount,
        deposit_name=match.group("deposit").strip(" «»\"'"),
        payment_label=payment_label,
    )


def _deposit_alias(value: str) -> str:
    normalized = " ".join(value.casefold().strip(" «»\"'").split())
    return _DEPOSIT_PREFIX_RE.sub("", normalized)


class DepositPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assets = AssetRepository(session)
        self._categories = CategoryRepository(session)
        self._transactions = TransactionRepository(session)

    async def apply(
        self,
        user_id: int,
        draft: DepositPaymentDraft,
    ) -> DepositPaymentResult:
        if draft.amount <= 0:
            raise DepositPaymentError("Сумма должна быть больше нуля.")

        deposits = await self._assets.list_deposits(user_id)
        requested = _deposit_alias(draft.deposit_name)
        matches = [
            item
            for item in deposits
            if requested in {_deposit_alias(item.name), item.name.casefold()}
        ]
        if len(matches) != 1:
            raise DepositPaymentError(
                "Не нашёл один подходящий депозит. Укажите его точное название."
            )
        deposit = await self._session.get(Deposit, matches[0].id, with_for_update=True)
        if deposit is None or deposit.user_id != user_id:
            raise DepositPaymentError("Депозит не найден.")
        if deposit.currency != "KZT":
            raise DepositPaymentError(
                "Автоматическая оплата пока поддерживается только из депозита в тенге."
            )

        previous_balance = float(deposit.balance)
        if previous_balance < draft.amount:
            raise DepositPaymentError(
                f"Недостаточно денег: в депозите {previous_balance:,.0f} ₸."
                .replace(",", " ")
            )

        category = await self._categories.get_or_create(
            user_id, "несие мен бөліп төлеу"
        )
        deposit.balance = previous_balance - draft.amount
        transaction = await self._transactions.create(
            user_id=user_id,
            category_id=category.id,
            amount=draft.amount,
            tx_type=TransactionType.expense,
            description=draft.payment_label,
        )
        await self._session.commit()
        return DepositPaymentResult(deposit, transaction, previous_balance)
