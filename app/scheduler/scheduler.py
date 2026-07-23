"""APScheduler setup for the background jobs."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from app.core.config import settings
from app.scheduler.jobs import (
    check_budgets,
    compound_deposit_interest,
    daily_reminder,
    weekly_digest,
)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Configure and return (unstarted) scheduler bound to ``bot``.

    * Budget check — daily at 20:00 local time.
    * Weekly digest — Sundays at 19:00 local time.
    """
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    scheduler.add_job(
        compound_deposit_interest,
        trigger=CronTrigger(hour=0, minute=10),
        id="compound_deposit_interest",
        replace_existing=True,
    )
    scheduler.add_job(
        check_budgets,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        id="daily_budget_check",
        replace_existing=True,
    )
    scheduler.add_job(
        weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=19, minute=0),
        args=[bot],
        id="weekly_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_reminder,
        trigger=CronTrigger(hour=21, minute=0),
        args=[bot],
        id="daily_reminder",
        replace_existing=True,
    )
    return scheduler
