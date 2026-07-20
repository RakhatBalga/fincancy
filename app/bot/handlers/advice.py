"""AI advice and rule-based coaching: /advice, /rule, /benchmark."""

from __future__ import annotations

import html
import re

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import (
    format_advice,
    format_anomalies,
    format_benchmark,
    format_rule,
)
from app.bot.keyboards import AI_BUTTONS
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
        await message.answer("Алдымен /start басыңыз.")
    return user


@router.message(Command("rule"))
async def cmd_rule(message: Message, session: AsyncSession) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    rule = await AdvisorService(session).fifty_thirty_twenty(user)
    if rule is None:
        await message.answer(
            "Кіріс керек. Жай түсімді жаз, мысалы "
            "<i>жалақы 150000</i> немесе <i>стипендия 40000</i> — ереже "
            "өзі қайта есептеледі. Немесе күтілетінін қой: <code>/income 190000</code>."
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
        await message.answer("Айда шығын жоқ — салыстыратын ештеңе жоқ.")
        return
    await message.answer(format_benchmark(rows))


@router.message(Command("advice"))
@router.message(F.text.in_(AI_BUTTONS))
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
            "💡 Кірісті <code>/income 400000</code> командасымен көрсет — "
            "50/30/20 ережесі бойынша талдау қосамын."
        )

    # Send each block as its own message so a long AI review can't push the
    # whole thing past Telegram's 4096-char limit.
    for part in parts:
        await _safe_send(message, part)


def _plain(text: str) -> str:
    """Strip HTML tags for the plain-text fallback."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def _safe_send(message: Message, text: str) -> None:
    """Send text in <=4000-char chunks, falling back to plain on HTML errors."""
    for i in range(0, len(text), 4000):
        chunk = text[i : i + 4000]
        try:
            await message.answer(chunk)
        except TelegramBadRequest:
            await message.answer(_plain(chunk))
