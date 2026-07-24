"""Free-text transaction capture and inline confirmation flow."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import format_confirmation
from app.bot.keyboards import (
    CONFIRM_PREFIX,
    RECAT_PREFIX,
    SETCAT_PREFIX,
    category_picker_keyboard,
    confirm_keyboard,
)
from app.repositories.category_repo import CategoryRepository
from app.repositories.transaction_repo import TransactionRepository
from app.services.deposit_payment_service import (
    DepositPaymentError,
    DepositPaymentService,
    looks_like_deposit_payment,
    parse_deposit_payment,
)
from app.services.parser_service import ExpenseParseError, ParserService
from app.services.transaction_service import TransactionService
from app.services.user_service import UserService

router = Router(name="transactions")
log = structlog.get_logger(__name__)

# Free-text phrases that mean "delete my last entry" rather than a new one.
_UNDO_WORDS = ("удали", "отмени", "убери", "отмена", "жой", "өшір", "болдырма", "delete", "undo")

# Phrases meaning "edit/reclassify an existing entry" — must NOT be parsed as
# a brand-new transaction (that would silently duplicate the amount).
_EDIT_WORDS = ("смени", "поменяй", "измени", "исправь", "переклассифи", "өзгерт", "ауыстыр", "түзет")


def _is_undo(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in _UNDO_WORDS)


def _is_edit_command(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in _EDIT_WORDS)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message, session: AsyncSession, parser: ParserService
) -> None:
    """Parse any non-command text as a transaction and ask to confirm."""
    assert message.from_user is not None and message.text is not None

    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Алдымен /start басыңыз.")
        return

    if looks_like_deposit_payment(message.text):
        draft = parse_deposit_payment(message.text)
        if draft is None:
            await message.answer(
                "Не понял составную операцию. Напишите, например: "
                "<i>вывел 53к из Депозита 1 и оплатил рассрочку Kaspi</i>."
            )
            return
        try:
            result = await DepositPaymentService(session).apply(user.id, draft)
        except DepositPaymentError as exc:
            await message.answer(str(exc))
            return
        amount = f"{draft.amount:,.0f}".replace(",", " ")
        previous = f"{result.previous_balance:,.0f}".replace(",", " ")
        current = f"{float(result.deposit.balance):,.0f}".replace(",", " ")
        await message.answer(
            "✅ <b>Перевод и платёж сохранены</b>\n"
            f"{result.deposit.name}: {previous} → {current} ₸\n"
            f"{draft.payment_label.capitalize()}: {amount} ₸\n"
            "Доход не создавался."
        )
        return

    # Natural-language "undo": delete the most recent transaction.
    if _is_undo(message.text):
        recent = await TransactionRepository(session).list_recent(user.id, 1)
        if not recent:
            await message.answer("Жоятын ештеңе жоқ — операциялар әзірге жоқ.")
            return
        await TransactionService(session).delete(user.id, recent[0].id)
        await message.answer("🗑 Соңғы операция жойылды.")
        return

    # "смени/поменяй/исправь X" — user wants to edit an existing entry, not
    # log a new one. Parsing this as a transaction would silently duplicate
    # the amount, so redirect to the actual editing flow instead.
    if _is_edit_command(message.text):
        await message.answer(
            "Бар операцияны мәтінмен өзгерту мүмкін емес — /recent аш, "
            "керек жазбаны тауып, астындағы ✏️/🗑 батырмаларын қолдан "
            "(санатты өзгерту үшін — жаңа растаудың астындағы «Санат» батырмасын)."
        )
        return

    try:
        parsed = await parser.parse(message.text)
    except ExpenseParseError:
        await message.answer(
            "Шығынды тани алмадым. Былай көр: <i>кофе 800</i>."
        )
        return
    except Exception:  # noqa: BLE001 - surface AI/transport failures gracefully
        log.exception("parse_failed", text=message.text)
        await message.answer(
            "⏳ Gemini қазір шамадан тыс жүктелген. Хабарды бірнеше "
            "секундтан кейін қайта жібер."
        )
        return

    # Persist immediately; the inline keyboard lets the user re-categorize.
    transaction = await TransactionService(session).add_from_parsed(user.id, parsed)
    await message.answer(
        format_confirmation(parsed, user.currency),
        reply_markup=confirm_keyboard(transaction.id),
    )


@router.callback_query(F.data.startswith(f"{CONFIRM_PREFIX}:"))
async def on_confirm(callback: CallbackQuery) -> None:
    await callback.answer("Сақталды ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(f"{RECAT_PREFIX}:"))
async def on_recategorize(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    transaction_id = int(callback.data.split(":")[1])

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Алдымен /start басыңыз.", show_alert=True)
        return

    categories = await CategoryRepository(session).list_for_user(user.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=category_picker_keyboard(transaction_id, categories)
        )


@router.callback_query(F.data.startswith(f"{SETCAT_PREFIX}:"))
async def on_set_category(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    _, raw_tx, raw_cat = callback.data.split(":")

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Алдымен /start басыңыз.", show_alert=True)
        return

    updated = await TransactionService(session).change_category(
        user_id=user.id,
        transaction_id=int(raw_tx),
        category_id=int(raw_cat),
    )
    if updated is None:
        await callback.answer("Санатты өзгерту мүмкін болмады.", show_alert=True)
        return

    await callback.answer("Санат жаңартылды ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
