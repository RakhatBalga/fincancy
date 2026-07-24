"""Helpers for computing period boundaries in the app timezone."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.models import User

_TZ = ZoneInfo(settings.tz)


def _now() -> datetime:
    return datetime.now(tz=_TZ)


def today() -> date:
    return _now().date()


def now() -> datetime:
    """Current application time with timezone information."""
    return _now()


def today_range() -> tuple[datetime, datetime]:
    """``[start of today, start of tomorrow)`` in the app timezone."""
    now = _now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def week_range() -> tuple[datetime, datetime]:
    """Current ISO week ``[Monday 00:00, next Monday 00:00)``."""
    now = _now()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def previous_week_range() -> tuple[datetime, datetime]:
    """The full ISO week before the current one."""
    start, end = week_range()
    return start - timedelta(days=7), start


def month_range() -> tuple[datetime, datetime]:
    """Current calendar month ``[1st 00:00, 1st of next month 00:00)``."""
    now = _now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def financial_cycle_range(user: User) -> tuple[datetime, datetime]:
    """Current salary-based cycle, falling back to the calendar month."""
    if user.financial_cycle_started_at is None:
        return month_range()
    start = user.financial_cycle_started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=_TZ)
    return start.astimezone(_TZ), _now() + timedelta(days=1)


def current_month_key() -> str:
    """``"YYYY-MM"`` key for the current month (used by budgets)."""
    return _now().strftime("%Y-%m")


def month_range_offset(months_ago: int) -> tuple[datetime, datetime]:
    """Range for a month ``months_ago`` months before the current one.

    ``months_ago=0`` is the current month, ``1`` the previous, etc.
    """
    now = _now()
    year, month = now.year, now.month - months_ago
    while month <= 0:
        month += 12
        year -= 1
    start = now.replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if month == 12:
        end = start.replace(year=year + 1, month=1)
    else:
        end = start.replace(month=month + 1)
    return start, end


def days_ago(days: int) -> datetime:
    """Timestamp ``days`` days before now (for lookback windows)."""
    return _now() - timedelta(days=days)
