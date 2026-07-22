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
    format_benchmark,
    format_rule,
)
from app.bot.keyboards import AI_BUTTONS
from app.db.models import User
from app.services.advisor_service import AdvisorService, build_asset_advice_summary
from app.services.analytics_service import AnalyticsService
from app.services.asset_service import AssetService
from app.services.market_data import MarketDataError, YahooFinanceService
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
async def cmd_advice(
    message: Message,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    user = await _require_user(message, session)
    if user is None:
        return

    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, "typing")

    advisor = AdvisorService(session)
    asset_context = None
    try:
        asset_service = AssetService(session, market)
        wealth = await asset_service.wealth(user.id)
        goals = await asset_service.goals(user.id)
        asset_context = build_asset_advice_summary(wealth, goals)
    except MarketDataError:
        log.warning("asset_quotes_unavailable_for_advice", user_id=user.id)

    try:
        advice = await advisor.monthly_advice(user, asset_context)
    except Exception:  # noqa: BLE001 - keep the bot responsive on AI failures
        log.exception("compact_advice_failed", user_id=user.id)
        await message.answer("Не удалось получить мнение ИИ. Попробуйте чуть позже.")
        return
    await _safe_send(message, format_advice(advice))


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
