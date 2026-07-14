"""AI advice and rule-based coaching: /advice, /rule, /benchmark."""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import (
    format_advice,
    format_anomalies,
    format_benchmark,
    format_rule,
)
from app.bot.keyboards import BTN_AI
from app.db.models import User
from app.services.advisor_service import AdvisorService
from app.services.analytics_service import AnalyticsService
from app.services.user_service import UserService

router = Router(name="advice")
log = structlog.get_logger(__name__)


async def _require_user(message: Message, session: AsyncSession) -> User | None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала выполни /start.")
    return user


@router.message(Command("rule"))
async def cmd_rule(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    rule = await AdvisorService(session).fifty_thirty_twenty(user)
    if rule is None:
        await message.answer(
            "Нужен доход. Просто запиши поступление, например "
            "<i>зарплата 150000</i> или <i>стипендия 40000</i> — правило "
            "пересчитается само. Либо задай ожидаемый: <code>/income 190000</code>."
        )
        return
    await message.answer(format_rule(rule, user.currency))


@router.message(Command("benchmark"))
async def cmd_benchmark(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    rows = await AdvisorService(session).benchmark(user)
    shares = await AnalyticsService(session).month_shares(user)
    if not shares:
        await message.answer("Нет трат за месяц — не с чем сравнивать.")
        return
    await message.answer(format_benchmark(rows))


@router.message(Command("advice"))
@router.message(F.text == BTN_AI)
async def cmd_advice(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return

    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, "typing")

    advisor = AdvisorService(session)
    analytics = AnalyticsService(session)

    parts: list[str] = []

    rule = await advisor.fifty_thirty_twenty(user)
    if rule is not None:
        parts.append(format_rule(rule, user.currency))

    anomalies = await analytics.detect_anomalies(user)
    if anomalies:
        parts.append(format_anomalies(anomalies, user.currency))

    advice = await advisor.monthly_advice(user)
    parts.append(format_advice(advice))

    if rule is None:
        parts.append(
            "💡 Подскажи доход командой <code>/income 400000</code> — "
            "добавлю разбор по правилу 50/30/20."
        )

    await message.answer("\n\n".join(parts))
