"""``/today``, ``/week``, ``/month`` — period spending reports."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import format_period_report
from app.bot.keyboards import MONTH_BUTTONS, TODAY_BUTTONS
from app.services.analytics_service import AnalyticsService
from app.services.user_service import UserService

router = Router(name="reports")


async def _require_user(message: Message, session: AsyncSession):
    """Return the registered user or prompt to run /start."""
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Алдымен /start басыңыз.")
    return user


@router.message(Command("today"))
@router.message(F.text.in_(TODAY_BUTTONS))
async def cmd_today(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    report = await AnalyticsService(session).today(user)
    await message.answer(format_period_report(report))


@router.message(Command("week"))
async def cmd_week(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    report = await AnalyticsService(session).week(user)
    await message.answer(format_period_report(report))


@router.message(Command("month"))
@router.message(F.text.in_(MONTH_BUTTONS))
async def cmd_month(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    report = await AnalyticsService(session).month(user)
    await message.answer(format_period_report(report))
