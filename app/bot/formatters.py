"""Render domain objects into Telegram-ready text tables."""

from __future__ import annotations

from app.db.models import Transaction
from app.services.advisor_service import RuleBreakdown
from app.services.budget_service import BudgetAlert
from app.services.schemas import ParsedTransaction, PeriodReport


def format_amount(value: float, currency: str) -> str:
    """Format money with a thin space thousands separator."""
    return f"{value:,.0f}".replace(",", " ") + f" {currency}"


def format_confirmation(parsed: ParsedTransaction, currency: str) -> str:
    kind = "Доход" if parsed.type.value == "income" else "Расход"
    text = (
        f"<b>{kind}</b>\n"
        f"Сумма: {format_amount(parsed.amount, currency)}\n"
        f"Категория: {parsed.category}\n"
        f"Описание: {parsed.description or '—'}"
    )
    if parsed.confidence == "low":
        text += "\n\n⚠️ Не уверен — проверь сумму и категорию."
    return text


def format_period_report(report: PeriodReport) -> str:
    """Render a :class:`PeriodReport` as a monospace text table."""
    if not report.rows:
        return f"<b>{report.title}</b>\nПока нет трат за этот период."

    lines = [
        f"<b>{report.title}</b>",
        f"Всего: {format_amount(report.total, report.currency)}",
        "",
        "<pre>",
        f"{'Категория':<14}{'Сумма':>12}{'%':>6}",
    ]
    for row in report.rows:
        amount = f"{row.total:,.0f}".replace(",", " ")
        lines.append(f"{row.name[:14]:<14}{amount:>12}{row.percent:>5.0f}%")
    lines.append("</pre>")
    return "\n".join(lines)


def format_budget_alert(alert: BudgetAlert, currency: str) -> str:
    icon = "🚨" if alert.level == "exceeded" else "⚠️"
    verb = "превышен" if alert.level == "exceeded" else "почти исчерпан"
    return (
        f"{icon} Бюджет {verb}: <b>{alert.category_name}</b>\n"
        f"Потрачено {format_amount(alert.spent, currency)} "
        f"из {format_amount(alert.limit, currency)} "
        f"({alert.ratio * 100:.0f}%)"
    )


def _verdict(actual_pct: float, target_pct: float, lower_is_better: bool) -> str:
    diff = actual_pct - target_pct
    if lower_is_better:
        return "✅ в норме" if diff <= 2 else f"⚠️ выше цели на {diff:.0f} п.п."
    return "✅ в норме" if diff >= -2 else f"⚠️ ниже цели на {-diff:.0f} п.п."


def format_rule(rule: RuleBreakdown, currency: str) -> str:
    """Render the 50/30/20 breakdown."""
    source = "получено в этом месяце" if rule.income_is_actual else "ожидаемый доход"
    return (
        "📊 <b>Правило 50/30/20</b> (доход "
        f"{format_amount(rule.income, currency)}, {source})\n"
        f"Нужное: {format_amount(rule.needs, currency)} "
        f"({rule.needs_pct:.0f}% / цель 50%) — "
        f"{_verdict(rule.needs_pct, 50, lower_is_better=True)}\n"
        f"Хотелки: {format_amount(rule.wants, currency)} "
        f"({rule.wants_pct:.0f}% / цель 30%) — "
        f"{_verdict(rule.wants_pct, 30, lower_is_better=True)}\n"
        f"Остаётся: {format_amount(rule.savings, currency)} "
        f"({rule.savings_pct:.0f}% / цель 20%) — "
        f"{_verdict(rule.savings_pct, 20, lower_is_better=False)}"
    )


def format_anomalies(anomalies: list[dict[str, object]], currency: str) -> str:
    if not anomalies:
        return "✅ Резких скачков трат в этом месяце нет."
    lines = ["📈 <b>Необычный рост трат</b> (к твоему среднему):"]
    for a in anomalies[:5]:
        cur = format_amount(float(a["current"]), currency)  # type: ignore[arg-type]
        ratio = float(a["ratio"])  # type: ignore[arg-type]
        lines.append(f"• {a['category']}: {cur} — в {ratio:.1f}× больше обычного")
    return "\n".join(lines)


def format_subscriptions(subs: list[dict[str, object]], currency: str) -> str:
    if not subs:
        return "Регулярных платежей пока не нашёл (нужно ≥2 месяцев истории)."
    total = sum(float(s["amount"]) for s in subs)  # type: ignore[arg-type]
    lines = [
        f"🔁 <b>Похоже на подписки</b> — ~{format_amount(total, currency)}/мес:"
    ]
    for s in subs[:10]:
        amount = format_amount(float(s["amount"]), currency)  # type: ignore[arg-type]
        lines.append(f"• {s['description']}: {amount} × {s['months']} мес")
    return "\n".join(lines)


def format_benchmark(rows: list[tuple[str, float, float]]) -> str:
    """Compare user category shares vs KZ reference shares."""
    lines = [
        "🇰🇿 <b>Ты vs среднее по Казахстану</b> (доля расходов, %)",
        "<pre>",
        f"{'Категория':<14}{'Ты':>6}{'РК':>6}",
    ]
    for name, user_pct, kz_pct in rows:
        lines.append(f"{name[:14]:<14}{user_pct:>5.0f}%{kz_pct:>5.0f}%")
    lines.append("</pre>")
    lines.append(
        "<i>Сравниваются доли, а не суммы — так честно при любом доходе.</i>"
    )
    return "\n".join(lines)


def format_advice(advice: str) -> str:
    return f"🧠 <b>Совет по месяцу</b>\n\n{advice}"


def format_recent(transactions: list[Transaction], currency: str) -> str:
    if not transactions:
        return "Пока нет записанных трат."
    return "🧾 <b>Последние операции</b>\n(нажми ✏️ чтобы изменить сумму, 🗑 чтобы удалить)"


def format_transaction_line(tx: Transaction, currency: str) -> str:
    sign = "−" if tx.type.value == "expense" else "+"
    desc = tx.description or "—"
    when = tx.created_at.strftime("%d.%m %H:%M")
    return f"{when}  {sign}{format_amount(float(tx.amount), currency)}  {desc}"


def format_weekly_digest(digest: dict[str, object]) -> str:
    """Render the weekly comparison digest."""
    currency = str(digest["currency"])
    current = float(digest["current_total"])  # type: ignore[arg-type]
    change = digest["change_percent"]
    top = digest["top"]  # list[tuple[str, float]]

    lines = [
        "🗓 <b>Итоги недели</b>",
        f"Потрачено: {format_amount(current, currency)}",
    ]
    if change is None:
        lines.append("Сравнить не с чем — это первая неделя с тратами.")
    else:
        change_f = float(change)
        arrow = "🔺" if change_f > 0 else ("🔻" if change_f < 0 else "▪️")
        lines.append(f"К прошлой неделе: {arrow} {abs(change_f):.0f}%")

    if top:
        lines.append("\nТоп категорий:")
        for name, amount in list(top)[:5]:  # type: ignore[arg-type]
            lines.append(f"• {name}: {format_amount(float(amount), currency)}")
    return "\n".join(lines)
