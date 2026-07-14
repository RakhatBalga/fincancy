"""Coaching layer: 50/30/20 rule + AI-generated monthly advice.

The rule math is pure and deterministic; the AI call turns the numbers (plus
anomalies and subscriptions) into a few concrete, human recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TransactionType, User
from app.repositories.transaction_repo import TransactionRepository
from app.services import benchmarks, gemini, periods
from app.services.analytics_service import AnalyticsService

log = structlog.get_logger(__name__)

# Target shares of income for the 50/30/20 rule.
TARGET_NEEDS = 0.50
TARGET_WANTS = 0.30
TARGET_SAVINGS = 0.20


@dataclass(slots=True)
class RuleBreakdown:
    """Result of the 50/30/20 evaluation for the current month."""

    income: float
    needs: float
    wants: float
    savings: float  # income − expenses (can be negative)
    needs_pct: float
    wants_pct: float
    savings_pct: float
    # True if `income` is the sum of income actually logged this month;
    # False if it fell back to the declared /income baseline.
    income_is_actual: bool


_ADVICE_SYSTEM = """
Ты — финансовый коуч для пользователя из Казахстана. На вход — сводка расходов
за месяц (категории, доли, доход, правило 50/30/20, аномалии, подписки).

Дай ровно 3 коротких конкретных совета на русском, по одному в строке,
каждый начинается с "• ". Опирайся на цифры из сводки, называй конкретные
категории и суммы. Тон — дружелюбный, уважительный, без морализаторства.
Не выдумывай данных, которых нет в сводке. Валюта — тенге (₸).

ВАЖНО про обязательства:
- "помощь семье" и "кредиты и рассрочка" — это ОБЯЗАТЕЛЬСТВА, а не хотелки.
  НЕ предлагай "просто сократить" помощь родным или перестать платить долг.
- Для долгов уместны советы: рефинансирование/объединение рассрочек, досрочное
  закрытие самой дорогой, план погашения.
- Экономию ищи прежде всего в дискреционных тратах: еда вне дома, развлечения,
  подписки, такси, одежда, подарки.
- Если обязательные траты (нужное + долги + помощь семье) превышают доход,
  честно и спокойно скажи об этом и предложи реалистичные шаги, включая
  возможность дополнительного дохода. Без чувства вины.
""".strip()


class AdvisorService:
    """Builds the 50/30/20 breakdown and the monthly AI advice."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)
        self._analytics = AnalyticsService(session)

    async def fifty_thirty_twenty(self, user: User) -> RuleBreakdown | None:
        """Evaluate the 50/30/20 rule for this month.

        Income is taken from the actual income transactions logged this month;
        if none yet, it falls back to the declared ``/income`` baseline. So the
        rule updates itself as salary/stipend land — no monthly re-entry needed.
        Returns ``None`` if there is neither logged income nor a baseline.
        """
        start, end = periods.month_range()
        actual_income = await self._transactions.total_amount(
            user.id, TransactionType.income, start, end
        )
        baseline = float(user.monthly_income or 0.0)

        # Use the larger of the two: a small logged gift shouldn't override the
        # expected salary, but real income above the baseline should win.
        income = max(actual_income, baseline)
        income_is_actual = actual_income > 0 and actual_income >= baseline
        if income <= 0:
            return None

        groups = await self._analytics.group_totals(user)
        needs = groups.get("needs", 0.0)
        wants = groups.get("wants", 0.0)
        savings = income - (needs + wants)

        return RuleBreakdown(
            income=income,
            needs=needs,
            wants=wants,
            savings=savings,
            needs_pct=needs / income * 100.0,
            wants_pct=wants / income * 100.0,
            savings_pct=savings / income * 100.0,
            income_is_actual=income_is_actual,
        )

    async def monthly_advice(self, user: User) -> str:
        """Generate 3 concrete recommendations from this month's data (AI)."""
        summary = await self._build_summary(user)
        if summary is None:
            return "Пока мало данных за месяц — запиши несколько трат, и я дам совет."

        advice = await gemini.generate_text(summary, _ADVICE_SYSTEM)
        log.info("monthly_advice_generated", user_id=user.id)
        return advice or "Не получилось сформировать совет, попробуй позже."

    async def _build_summary(self, user: User) -> str | None:
        """Assemble a compact plain-text summary fed to the model."""
        start, end = periods.month_range()
        rows = await self._transactions.total_by_category(
            user.id, TransactionType.expense, start, end
        )
        if not rows:
            return None

        total = sum(a for _, a in rows)
        lines = [f"Расходы за месяц: {total:.0f} ₸.", "Категории:"]
        for name, amount in rows:
            share = amount / total * 100.0 if total else 0.0
            lines.append(f"- {name}: {amount:.0f} ₸ ({share:.0f}%)")

        rule = await self.fifty_thirty_twenty(user)
        if rule is not None:
            lines.append(
                f"Доход: {rule.income:.0f} ₸. "
                f"Нужное {rule.needs_pct:.0f}% (цель 50%), "
                f"хотелки {rule.wants_pct:.0f}% (цель 30%), "
                f"остаётся {rule.savings_pct:.0f}% (цель 20%)."
            )

        anomalies = await self._analytics.detect_anomalies(user)
        if anomalies:
            joined = ", ".join(
                f"{a['category']} +{(a['ratio'] - 1) * 100:.0f}%"  # type: ignore[operator]
                for a in anomalies[:3]
            )
            lines.append(f"Резкий рост vs обычного: {joined}.")

        subs = await self._analytics.detect_subscriptions(user)
        if subs:
            sub_total = sum(float(s["amount"]) for s in subs)  # type: ignore[arg-type]
            lines.append(
                f"Похоже на подписки/регулярные платежи на ~{sub_total:.0f} ₸/мес."
            )

        return "\n".join(lines)

    async def benchmark(self, user: User) -> list[tuple[str, float, float]]:
        """Compare the user's category shares with the KZ reference (%)."""
        shares = await self._analytics.month_shares(user)
        return benchmarks.compare_shares(shares)
