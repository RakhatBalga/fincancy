"""``/recent`` — list, delete, and edit recent transactions."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import (
    format_amount,
    format_recent,
    format_transaction_line,
)
from app.bot.keyboards import (
    MENU_BUTTONS,
    RESET_PREFIX,
    TXDEL_PREFIX,
    TXEDIT_PREFIX,
    reset_confirm_keyboard,
    transaction_row_keyboard,
)
from app.repositories.transaction_repo import TransactionRepository
from app.services.transaction_service import TransactionService
from app.services.user_service import UserService

router = Router(name="manage")


class EditAmount(StatesGroup):
    """Waiting for the user to type a new amount for a transaction."""

    waiting = State()


@router.message(Command("recent"))
async def cmd_recent(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return

    transactions = await TransactionRepository(session).list_recent(user.id, 10)
    if not transactions:
        await message.answer("Пока нет записанных трат.")
        return

    await message.answer(format_recent(transactions, user.currency))
    for tx in transactions:
        await message.answer(
            format_transaction_line(tx, user.currency),
            reply_markup=transaction_row_keyboard(tx.id),
        )


@router.callback_query(F.data.startswith(f"{TXDEL_PREFIX}:"))
async def on_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    transaction_id = int(callback.data.split(":")[1])

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выполни /start.", show_alert=True)
        return

    deleted = await TransactionService(session).delete(user.id, transaction_id)
    if not deleted:
        await callback.answer("Не удалось удалить.", show_alert=True)
        return

    await callback.answer("Удалено 🗑")
    if isinstance(callback.message, Message):
        await callback.message.edit_text("<s>операция удалена</s>")


@router.callback_query(F.data.startswith(f"{TXEDIT_PREFIX}:"))
async def on_edit_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    assert callback.data is not None
    transaction_id = int(callback.data.split(":")[1])
    await state.set_state(EditAmount.waiting)
    await state.update_data(transaction_id=transaction_id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Введи новую сумму числом (например 1200):")


@router.message(
    StateFilter(EditAmount.waiting),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def on_edit_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.from_user is not None and message.text is not None

    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await state.clear()
        await message.answer(
            "Это не похоже на сумму — отменил. Открой /recent и попробуй снова."
        )
        return

    data = await state.get_data()
    transaction_id = int(data["transaction_id"])
    await state.clear()

    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return

    updated = await TransactionService(session).update_amount(
        user.id, transaction_id, amount
    )
    if updated is None:
        await message.answer("Не удалось обновить сумму.")
        return

    await message.answer(
        f"✅ Сумма обновлена: {format_amount(amount, user.currency)}"
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return

    await message.answer(
        "⚠️ <b>Удалить ВСЕ траты, доходы и бюджеты?</b>\n"
        "Это действие необратимо. Профиль, категории и доход останутся.",
        reply_markup=reset_confirm_keyboard(),
    )


@router.callback_query(F.data == f"{RESET_PREFIX}:cancel")
async def on_reset_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Отменено — данные не тронуты.")


@router.callback_query(F.data == f"{RESET_PREFIX}:confirm")
async def on_reset_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.from_user is not None
    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выполни /start.", show_alert=True)
        return

    tx_count, budget_count = await TransactionService(session).reset_all(user.id)

    await callback.answer("Удалено")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"🗑 Удалено: {tx_count} операций, {budget_count} бюджетов.\n"
            "Можно начинать заново — просто пиши траты обычным текстом."
        )
