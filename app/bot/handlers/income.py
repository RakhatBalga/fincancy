"""``/income`` — set monthly income for the 50/30/20 advice.

Works two ways:
* ``/income 400000`` — sets it directly.
* ``/income`` alone — bot asks for the amount and the next number is stored
  (FSM waiting state), so replying with just ``125000`` works as expected.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import format_amount
from app.db.models import User
from app.services.user_service import UserService

router = Router(name="income")


class IncomeStates(StatesGroup):
    """Waiting for the user to type their monthly income."""

    waiting = State()


def _parse_amount(raw: str) -> float | None:
    try:
        return float(raw.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


async def _apply_income(
    message: Message, session: AsyncSession, user: User, amount: float
) -> None:
    try:
        await UserService(session).set_income(user, amount)
    except ValueError:
        await message.answer("Доход должен быть больше нуля.")
        return
    await message.answer(
        f"✅ Месячный доход сохранён: {format_amount(amount, user.currency)}\n"
        "Теперь доступна команда /rule (правило 50/30/20)."
    )


@router.message(Command("income"))
async def cmd_income(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    assert message.from_user is not None

    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return

    if not command.args:
        current = (
            format_amount(float(user.monthly_income), user.currency)
            if user.monthly_income
            else "не задан"
        )
        await state.set_state(IncomeStates.waiting)
        await message.answer(
            f"Текущий доход: {current}\n\n"
            "Введи месячный доход числом (например 400000):"
        )
        return

    amount = _parse_amount(command.args)
    if amount is None:
        await message.answer("Сумма должна быть числом. Например: /income 400000")
        return
    await _apply_income(message, session, user, amount)


@router.message(
    IncomeStates.waiting, F.text, ~F.text.startswith("/")
)
async def on_income_amount(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    assert message.from_user is not None and message.text is not None

    amount = _parse_amount(message.text)
    if amount is None:
        await message.answer("Нужно число. Попробуй ещё раз или отправь /income.")
        return

    await state.clear()
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
        return
    await _apply_income(message, session, user, amount)
