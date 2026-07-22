"""Coaching layer: 50/30/20 rule + AI-generated monthly advice.

The rule math is pure and deterministic; the AI call turns the numbers (plus
anomalies and subscriptions) into a few concrete, human recommendations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinancialGoal, TransactionType, User
from app.repositories.category_repo import CategoryRepository
from app.repositories.transaction_repo import TransactionRepository
from app.services import benchmarks, gemini, periods
from app.services.analytics_service import AnalyticsService
from app.services.asset_service import WealthSummary

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
    # Realistic reallocation of what's left after fixed obligations (needs),
    # split 30:20 between wants and savings — the "gramotno" plan.
    wants_ideal: float
    savings_ideal: float


_ADVICE_SYSTEM = """
Ты — внимательный финансовый коуч для пользователя из Казахстана. На вход —
подробная сводка за месяц (доходы по источникам, расходы по категориям с долями,
баланс, правило 50/30/20, аномалии, подписки, сравнение со средним по РК).

Дай РАЗВЁРНУТЫЙ разбор ПОЛНОСТЬЮ НА КАЗАХСКОМ ЯЗЫКЕ (қазақ тілінде) в таком
формате (используй HTML-теги <b>...</b> для заголовков, без markdown).
ВСЕ заголовки и весь текст — только по-казахски:

<b>Қорытынды</b>
2-3 предложения: доход, расходы, баланс. Честная и спокойная оценка ситуации.

<b>Не маңызды</b>
3-5 конкретных рекомендаций (не больше, не заполняй список ради количества —
лучше 3 сильных пункта, чем 5 с натяжкой), каждая с новой строки начинается
с "• ". В каждой — конкретная категория и сумма из сводки, и что именно сделать.
Сортируй по важности: сначала самое влияющее на баланс. Не предлагай урезать
категории, которые и так уже минимальны (несколько сотен-тысяч тенге) — это
не решает проблему, только создаёт видимость действия.

<b>Осы ақшаға қалай өмір сүрер едің</b>
Забудь про обязательства пользователя (кредиты, переводы, помощь семье) —
их здесь НЕ упоминай и НЕ резервируй под них деньги. Представь, что этот доход
месяца — твой собственный и это ВСЯ сумма, которая у тебя есть на месяц.
Распредели её целиком с нуля своими категориями и суммами в тенге так, как сам
считаешь разумным для нормальной жизни в Астане (транспорт, связь, немного
развлечений, обязательно откладывать на подушку и т.д.).

ВАЖНО: в сводке указано, платит ли пользователь за жильё и питание сам, или
это бесплатно (живёт с семьёй). Строго учти это:
- Если жильё бесплатно — НЕ включай строку аренды/жилья вообще.
- Если питание в основном бесплатно (дома) — НЕ включай крупную строку
  "питание/продукты"; можно оставить небольшую сумму на перекусы/кафе вне дома.
- Если пользователь платит сам — включи жильё и/или питание как обычные статьи.
Не выдумывай трат на то, что реально не нужно оплачивать.

Это твоя полностью независимая версия бюджета для этой суммы денег — не
привязывай её к тратам пользователя и ничего не сравнивай. Только твоя роспись.

<b>Келесі қадам</b>
Одно конкретное действие на этот месяц, с ориентиром в тенге.

Правила:
- Опирайся ТОЛЬКО на цифры из сводки, ничего не выдумывай. Валюта — тенге (₸).
- "отбасыға көмек" және "несие мен бөліп төлеу" — бұл МІНДЕТТЕМЕЛЕР, қалау емес.
  НЕ предлагай сократить помощь родным или перестать платить долг.
- Категории с пометкой [накопления] (например "депозит") — это деньги, которые
  человек УЖЕ отложил/инвестировал. Это хорошо, а не трата — НЕ предлагай их
  сократить и не считай хотелкой. Можно похвалить, если сумма заметная.
- Для долгов уместны: рефинансирование/объединение рассрочек, досрочное
  закрытие самой дорогой, план погашения.
- Үнемдеуді қосымша (дискреционды) шығындардан ізде: сырттағы тамақ,
  ойын-сауық, жазылымдар, такси, киім, сыйлықтар.
- Если обязательные траты превышают доход — скажи честно и спокойно, предложи
  реалистичные шаги, включая дополнительный доход. Без чувства вины и морализаторства.
""".strip()

_COMPACT_ADVICE_SYSTEM = """
Ты — спокойный и честный финансовый советник. Пользователь из Казахстана.
На входе будут расходы и доходы за месяц, депозиты, инвестиционный портфель,
реализованный и нереализованный P/L, общий капитал и финансовые цели.

Ответь ПО-РУССКИ, коротко и конкретно, только в таком формате:

<b>Коротко</b>
Два предложения с общей оценкой финансового положения.

<b>Что вижу</b>
Ровно 3 коротких пункта, каждый начинается с "• ". Обязательно оцени:
• соотношение депозитов и риск портфеля;
• результат инвестиций, включая реализованный и нереализованный P/L;
• близость к финансовой цели и достаточность текущего темпа.

<b>Следующий шаг</b>
Одно конкретное действие без длинного плана.

Правила:
- Весь ответ не длиннее 900 символов.
- Не повторяй все цифры из сводки; используй только ключевые.
- Не обещай доходность и не выдумывай данные.
- Не давай категоричных команд покупать или продавать конкретную акцию.
- Используй только Telegram HTML <b>, без markdown.
""".strip()


# Telegram's HTML parser only understands a small tag set (b, i, u, s, a,
# code, pre, span, blockquote) — anything else (p, ul, li, div, br, h1, ...)
# makes the whole message fail to send. Strip/convert those before sending.
_TAG_TO_NEWLINE = re.compile(r"</?(p|div|ul|ol|br|h[1-6])\b[^>]*>", re.IGNORECASE)
_LI_OPEN = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_LI_CLOSE = re.compile(r"</li>", re.IGNORECASE)


def _clean_markup(text: str) -> str:
    """Normalise the model's output to Telegram-HTML-friendly markup.

    Converts markdown bold to ``<b>``, unifies bullet markers to "• ", and
    strips block-level HTML tags (``<p>``, ``<ul>``, ``<li>``, ...) that
    Telegram's parser rejects, turning them into plain newlines/bullets.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = _LI_OPEN.sub("• ", text)
    text = _LI_CLOSE.sub("\n", text)
    text = _TAG_TO_NEWLINE.sub("\n", text)
    text = re.sub(r"(?m)^[ \t]*[*\-][ \t]+", "• ", text)
    # A <li> already followed by the model's own "• " leaves "• • " — collapse it.
    text = re.sub(r"•\s*•\s*", "• ", text)
    # Collapse runs of blank lines left behind by the tag stripping.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_asset_advice_summary(
    summary: WealthSummary, goals: list[FinancialGoal]
) -> str:
    """Build compact, factual asset context for the AI review."""
    lines = [
        "Активы:",
        f"- Общий капитал: {summary.total_kzt:.0f} KZT / {summary.total_usd:.2f} USD.",
        f"- Брокерский счёт: {summary.broker_total_usd:.2f} USD; "
        f"депозиты: {summary.deposits_kzt:.0f} KZT.",
    ]
    unrealized = sum(item.profit_usd for item in summary.positions)
    realized = (
        float(summary.broker_account.realized_pnl_usd) if summary.broker_account else 0
    )
    lines.append(
        f"- P/L: нереализованный {unrealized:+.2f} USD, "
        f"закрытые сделки {realized:+.2f} USD, общий {unrealized + realized:+.2f} USD."
    )
    if summary.positions:
        positions = ", ".join(
            f"{item.position.symbol} {item.value_usd:.2f} USD "
            f"({item.profit_percent:+.1f}%)"
            for item in summary.positions
        )
        lines.append(f"- Позиции: {positions}.")
    for goal in goals:
        current = summary.total_usd if goal.currency == "USD" else summary.total_kzt
        target = float(goal.target_amount)
        progress = current / target * 100 if target else 0
        lines.append(
            f"- Цель {goal.title}: {progress:.1f}% выполнено, "
            f"осталось {max(0, 100 - progress):.1f}%."
        )
    return "\n".join(lines)


class AdvisorService:
    """Builds the 50/30/20 breakdown and the monthly AI advice."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._transactions = TransactionRepository(session)
        self._categories = CategoryRepository(session)
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

        # Needs/obligations are fixed (rent, debt, family support) — the
        # realistic plan reallocates what's left after them, not the whole
        # income, since a 50%-needs target is moot once obligations exceed it.
        remaining_after_needs = income - needs
        if remaining_after_needs > 0:
            wants_ideal = remaining_after_needs * (
                TARGET_WANTS / (TARGET_WANTS + TARGET_SAVINGS)
            )
            savings_ideal = remaining_after_needs - wants_ideal
        else:
            wants_ideal = 0.0
            savings_ideal = remaining_after_needs  # deficit, negative

        return RuleBreakdown(
            income=income,
            needs=needs,
            wants=wants,
            savings=savings,
            needs_pct=needs / income * 100.0,
            wants_pct=wants / income * 100.0,
            savings_pct=savings / income * 100.0,
            income_is_actual=income_is_actual,
            wants_ideal=wants_ideal,
            savings_ideal=savings_ideal,
        )

    async def monthly_advice(self, user: User, asset_summary: str | None = None) -> str:
        """Generate a compact review of cash flow, assets, and goals."""
        summary = await self._build_summary(user, asset_summary)
        if summary is None:
            return "Ай бойы дерек аз — бірнеше шығын жаз, сонда кеңес беремін."

        advice = await gemini.generate_text(summary, _COMPACT_ADVICE_SYSTEM)
        log.info("monthly_advice_generated", user_id=user.id)
        if not advice:
            return "Кеңес құрастыра алмадым, кейінірек көр."
        return _clean_markup(advice)

    async def _build_summary(
        self, user: User, asset_summary: str | None = None
    ) -> str | None:
        """Assemble a compact plain-text summary fed to the model."""
        start, end = periods.month_range()
        rows = await self._transactions.total_by_category(
            user.id, TransactionType.expense, start, end
        )
        if not rows and not asset_summary:
            return None

        total = sum(a for _, a in rows)

        # Living situation — tells the hypothetical-budget section whether to
        # invent rent/food money the user doesn't actually spend.
        living_lines: list[str] = []
        if user.housing_is_free is True:
            living_lines.append("Жильё: бесплатно (живёт с семьёй/родителями).")
        elif user.housing_is_free is False:
            living_lines.append("Жильё: платит сам(а).")
        if user.food_is_free is True:
            living_lines.append("Питание: в основном бесплатно (дома).")
        elif user.food_is_free is False:
            living_lines.append("Питание: платит сам(а).")

        # Income sources + balance for the month.
        income_report, expense_total = await self._analytics.month_balance(user)
        lines: list[str] = list(living_lines)
        if income_report.rows:
            lines.append("Доходы за месяц по источникам:")
            for r in income_report.rows:
                lines.append(f"- {r.name}: {r.total:.0f} ₸")
            lines.append(f"Всего доходов: {income_report.total:.0f} ₸.")
        balance = income_report.total - expense_total
        lines.append(
            f"Баланс за месяц: {balance:.0f} ₸ "
            f"({'профицит' if balance >= 0 else 'дефицит'})."
        )

        category_groups = {
            c.name: c.group_type for c in await self._categories.list_for_user(user.id)
        }
        lines += [f"Расходы за месяц: {total:.0f} ₸.", "Категории расходов:"]
        for name, amount in rows:
            share = amount / total * 100.0 if total else 0.0
            group = category_groups.get(name)
            tag = (
                " [хотелка]"
                if group == "wants"
                else " [накопления]"
                if group == "savings"
                else ""
            )
            lines.append(f"- {name}: {amount:.0f} ₸ ({share:.0f}%){tag}")

        rule = await self.fifty_thirty_twenty(user)
        if rule is not None:
            lines.append(
                f"Доход: {rule.income:.0f} ₸. "
                f"Нужное (обязательства) {rule.needs:.0f} ₸ ({rule.needs_pct:.0f}%), "
                f"хотелки {rule.wants:.0f} ₸ ({rule.wants_pct:.0f}%), "
                f"осталось по факту {rule.savings:.0f} ₸ ({rule.savings_pct:.0f}%)."
            )
            lines.append(
                "План после обязательств (нужное менять нельзя, это "
                f"фиксированные платежи): из оставшихся "
                f"{rule.income - rule.needs:.0f} ₸ разумно направить "
                f"~{rule.wants_ideal:.0f} ₸ на хотелки и "
                f"~{rule.savings_ideal:.0f} ₸ отложить/накопить. "
                f"По факту на хотелки ушло {rule.wants:.0f} ₸, "
                f"отложилось фактически {rule.savings:.0f} ₸."
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
            names = ", ".join(str(s["description"]) for s in subs[:5])
            lines.append(
                f"Похоже на подписки/регулярные платежи на ~{sub_total:.0f} ₸/мес "
                f"({names})."
            )

        # Deviations from the KZ average (shares of spending).
        bench = await self.benchmark(user)
        deviations = [
            f"{name}: {u:.0f}% vs средних {kz:.0f}%"
            for name, u, kz in bench
            if abs(u - kz) >= 7
        ][:3]
        if deviations:
            lines.append("Отклонения от среднего по РК: " + "; ".join(deviations) + ".")

        if asset_summary:
            lines.extend(["", asset_summary])

        return "\n".join(lines)

    async def benchmark(self, user: User) -> list[tuple[str, float, float]]:
        """Compare the user's category shares with the KZ reference (%)."""
        shares = await self._analytics.month_shares(user)
        return benchmarks.compare_shares(shares)
