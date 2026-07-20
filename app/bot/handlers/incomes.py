"""``/incomes`` — income breakdown for the month + net balance."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import format_income_report
from app.bot.keyboards import INCOME_BUTTONS
from app.services.analytics_service import AnalyticsService
from app.services.user_service import UserService

router = Router(name="incomes")


@router.message(Command("incomes"))
@router.message(F.text.in_(INCOME_BUTTONS))
async def cmd_incomes(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Алдымен /start басыңыз.")
        return

    income_report, expense_total = await AnalyticsService(session).month_balance(user)
    await message.answer(format_income_report(income_report, expense_total))
