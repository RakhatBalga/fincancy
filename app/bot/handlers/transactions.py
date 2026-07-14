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
from app.services.parser_service import ExpenseParseError, ParserService
from app.services.transaction_service import TransactionService
from app.services.user_service import UserService

router = Router(name="transactions")
log = structlog.get_logger(__name__)

# Free-text phrases that mean "delete my last entry" rather than a new one.
_UNDO_WORDS = ("удали", "отмени", "убери", "отмена", "delete", "undo")


def _is_undo(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in _UNDO_WORDS)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message, session: AsyncSession, parser: ParserService
) -> None:
    """Parse any non-command text as a transaction and ask to confirm."""
    assert message.from_user is not None and message.text is not None

    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return

    # Natural-language "undo": delete the most recent transaction.
    if _is_undo(message.text):
        recent = await TransactionRepository(session).list_recent(user.id, 1)
        if not recent:
            await message.answer("Нечего удалять — операций пока нет.")
            return
        await TransactionService(session).delete(user.id, recent[0].id)
        await message.answer("🗑 Последняя операция удалена.")
        return

    try:
        parsed = await parser.parse(message.text)
    except ExpenseParseError:
        await message.answer(
            "Не смог распознать трату. Попробуй так: <i>кофе 800</i>."
        )
        return
    except Exception:  # noqa: BLE001 - surface AI/transport failures gracefully
        log.exception("parse_failed", text=message.text)
        await message.answer(
            "⏳ Gemini сейчас перегружен. Отправь сообщение ещё раз через "
            "пару секунд."
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
    await callback.answer("Сохранено ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith(f"{RECAT_PREFIX}:"))
async def on_recategorize(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    transaction_id = int(callback.data.split(":")[1])

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выполни /start.", show_alert=True)
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
        await callback.answer("Сначала выполни /start.", show_alert=True)
        return

    updated = await TransactionService(session).change_category(
        user_id=user.id,
        transaction_id=int(raw_tx),
        category_id=int(raw_cat),
    )
    if updated is None:
        await callback.answer("Не удалось изменить категорию.", show_alert=True)
        return

    await callback.answer("Категория обновлена ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
