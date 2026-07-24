"""Pure aggregation over transactions — period reports and weekly digests.

No AI at read time: everything here is deterministic SQL aggregation plus
arithmetic, so reports are cheap and reproducible.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TransactionType, User
from app.repositories.transaction_repo import TransactionRepository
from app.repositories.user_repo import UserRepository
from app.services import periods
from app.services.schemas import CategoryTotal, PeriodReport


class AnalyticsService:
    """Builds spending reports and digests from stored transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)
        self._users = UserRepository(session)

    async def period_report(
        self,
        user: User,
        title: str,
        start: datetime,
        end: datetime,
        tx_type: TransactionType = TransactionType.expense,
    ) -> PeriodReport:
        """Build a breakdown of spending by category for ``[start, end)``.

        Percentages are computed against the period total and always sum to
        ~100 (subject to rounding).
        """
        rows = await self._transactions.total_by_category(
            user.id, tx_type, start, end
        )
        total = sum(amount for _, amount in rows)

        category_totals = [
            CategoryTotal(
                name=name,
                total=amount,
                percent=(amount / total * 100.0) if total else 0.0,
            )
            for name, amount in rows
        ]
        return PeriodReport(
            title=title,
            total=total,
            currency=user.currency,
            rows=category_totals,
        )

    async def today(self, user: User) -> PeriodReport:
        start, end = periods.today_range()
        return await self.period_report(user, "Бүгін", start, end)

    async def week(self, user: User) -> PeriodReport:
        start, end = periods.week_range()
        return await self.period_report(user, "Осы апта", start, end)

    async def month(self, user: User) -> PeriodReport:
        start, end = periods.financial_cycle_range(user)
        return await self.period_report(user, "Осы қаржы циклі", start, end)

    async def income_month(self, user: User) -> PeriodReport:
        """Income (not expenses) broken down by category for this month."""
        start, end = periods.financial_cycle_range(user)
        return await self.period_report(
            user, "Қаржы циклінің кірістері", start, end, TransactionType.income
        )

    async def month_balance(self, user: User) -> tuple[PeriodReport, float]:
        """Return ``(income_report, expense_total)`` for the current month."""
        start, end = periods.financial_cycle_range(user)
        income = await self.income_month(user)
        expense_total = await self._transactions.total_amount(
            user.id, TransactionType.expense, start, end
        )
        return income, expense_total

    async def has_spending_today(self, user: User) -> bool:
        """True if the user logged at least one expense today."""
        start, end = periods.today_range()
        total = await self._transactions.total_amount(
            user.id, TransactionType.expense, start, end
        )
        return total > 0

    async def month_shares(self, user: User) -> dict[str, float]:
        """Current-month expense share (%) per category name."""
        start, end = periods.financial_cycle_range(user)
        rows = await self._transactions.total_by_category(
            user.id, TransactionType.expense, start, end
        )
        total = sum(a for _, a in rows)
        if total <= 0:
            return {}
        return {name: amount / total * 100.0 for name, amount in rows}

    async def group_totals(self, user: User) -> dict[str, float]:
        """Current-month expense totals by 50/30/20 bucket."""
        start, end = periods.financial_cycle_range(user)
        return await self._transactions.total_by_group(
            user.id, TransactionType.expense, start, end
        )

    async def detect_anomalies(
        self, user: User, lookback_months: int = 3, threshold: float = 1.4
    ) -> list[dict[str, object]]:
        """Categories where this month's spend far exceeds the recent norm.

        Compares the current month against the average of the previous
        ``lookback_months`` full months. Flags a category when current spend
        is at least ``threshold`` times its average and the increase is
        material (avoids noise on tiny amounts).
        """
        cur_start, cur_end = periods.month_range()
        current = dict(
            await self._transactions.total_by_category(
                user.id, TransactionType.expense, cur_start, cur_end
            )
        )

        # Accumulate per-category totals across the prior months.
        history: dict[str, float] = {}
        for offset in range(1, lookback_months + 1):
            start, end = periods.month_range_offset(offset)
            for name, amount in await self._transactions.total_by_category(
                user.id, TransactionType.expense, start, end
            ):
                history[name] = history.get(name, 0.0) + amount

        anomalies: list[dict[str, object]] = []
        for name, cur_amount in current.items():
            avg = history.get(name, 0.0) / lookback_months
            if avg <= 0:
                continue
            ratio = cur_amount / avg
            if ratio >= threshold and (cur_amount - avg) >= 1000:
                anomalies.append(
                    {
                        "category": name,
                        "current": cur_amount,
                        "average": avg,
                        "ratio": ratio,
                    }
                )
        anomalies.sort(key=lambda a: a["ratio"], reverse=True)  # type: ignore[arg-type]
        return anomalies

    async def detect_subscriptions(
        self, user: User, lookback_days: int = 100, min_months: int = 2
    ) -> list[dict[str, object]]:
        """Heuristic recurring-payment detector.

        Groups recent expenses by ``(description, amount)`` and reports those
        that appear in at least ``min_months`` distinct calendar months —
        a strong signal of a subscription or regular bill.
        """
        since = periods.days_ago(lookback_days)
        transactions = await self._transactions.list_since(
            user.id, TransactionType.expense, since
        )

        groups: dict[tuple[str, float], set[str]] = {}
        for tx in transactions:
            key = (
                (tx.description or "").strip().lower(),
                round(float(tx.amount)),
            )
            if not key[0]:
                continue
            groups.setdefault(key, set()).add(tx.created_at.strftime("%Y-%m"))

        subs: list[dict[str, object]] = []
        for (description, amount), months in groups.items():
            if len(months) >= min_months:
                subs.append(
                    {
                        "description": description,
                        "amount": float(amount),
                        "months": len(months),
                    }
                )
        subs.sort(key=lambda s: s["amount"], reverse=True)  # type: ignore[arg-type]
        return subs

    async def weekly_digest(self, user: User) -> dict[str, object]:
        """Compare this week's spending with last week's.

        Returns a dict with ``current_total``, ``previous_total``,
        ``change_percent`` and ``top`` (the ordered category rows for the
        current week). ``change_percent`` is ``None`` when there is no prior
        spending to compare against.
        """
        cur_start, cur_end = periods.week_range()
        prev_start, prev_end = periods.previous_week_range()

        current_rows = await self._transactions.total_by_category(
            user.id, TransactionType.expense, cur_start, cur_end
        )
        previous_rows = await self._transactions.total_by_category(
            user.id, TransactionType.expense, prev_start, prev_end
        )

        current_total = sum(a for _, a in current_rows)
        previous_total = sum(a for _, a in previous_rows)

        if previous_total > 0:
            change_percent: float | None = (
                (current_total - previous_total) / previous_total * 100.0
            )
        else:
            change_percent = None

        return {
            "current_total": current_total,
            "previous_total": previous_total,
            "change_percent": change_percent,
            "top": current_rows,
            "currency": user.currency,
        }
