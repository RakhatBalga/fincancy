"""Background jobs: daily budget checks and the weekly digest."""

from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.bot.formatters import format_budget_alert, format_weekly_digest
from app.db.base import async_session_factory
from app.repositories.user_repo import UserRepository
from app.services.analytics_service import AnalyticsService
from app.services.asset_service import AssetService
from app.services.budget_service import BudgetService
from app.services import periods

log = structlog.get_logger(__name__)

_REMINDER_TEXT = (
    "🌙 Бүгінгі шығындарды жазуды ұмытпа — жай жаз, мысалы "
    "<i>кешкі ас 3500</i>."
)


async def compound_deposit_interest() -> None:
    """Accrue due monthly interest for all rate-bearing deposits."""
    async with async_session_factory() as session:
        accrued = await AssetService(session).accrue_deposit_interest(
            periods.today()
        )
    log.info(
        "deposit_interest_compounded",
        deposits=len(accrued),
        months=sum(item.months for item in accrued),
    )


async def check_budgets(bot: Bot) -> None:
    """Daily: warn users whose category spending crossed 80% / 100%.

    Runs read-only aggregation per user and DMs any alerts. Blocked users
    (who stopped the bot) are skipped without failing the whole job.
    """
    async with async_session_factory() as session:
        users = await UserRepository(session).list_all()
        budget_service = BudgetService(session)

        for user in users:
            alerts = await budget_service.check_user(user)
            for alert in alerts:
                text = format_budget_alert(alert, user.currency)
                try:
                    await bot.send_message(user.telegram_id, text)
                except TelegramForbiddenError:
                    log.info("budget_alert_skipped_blocked", user_id=user.id)
                await asyncio.sleep(0.05)  # gentle rate limiting

    log.info("budget_check_done", users=len(users))


async def weekly_digest(bot: Bot) -> None:
    """Sunday evening: send each user a week-over-week spending digest."""
    async with async_session_factory() as session:
        users = await UserRepository(session).list_all()
        analytics = AnalyticsService(session)

        sent = 0
        for user in users:
            digest = await analytics.weekly_digest(user)
            if digest["current_total"] == 0 and digest["previous_total"] == 0:
                continue  # nothing to report
            try:
                await bot.send_message(user.telegram_id, format_weekly_digest(digest))
                sent += 1
            except TelegramForbiddenError:
                log.info("digest_skipped_blocked", user_id=user.id)
            await asyncio.sleep(0.05)

    log.info("weekly_digest_done", sent=sent)


async def daily_reminder(bot: Bot) -> None:
    """Evening nudge for users who logged no expense today."""
    async with async_session_factory() as session:
        users = await UserRepository(session).list_all()
        analytics = AnalyticsService(session)

        sent = 0
        for user in users:
            if await analytics.has_spending_today(user):
                continue
            try:
                await bot.send_message(user.telegram_id, _REMINDER_TEXT)
                sent += 1
            except TelegramForbiddenError:
                log.info("reminder_skipped_blocked", user_id=user.id)
            await asyncio.sleep(0.05)

    log.info("daily_reminder_done", sent=sent)
