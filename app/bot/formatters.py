"""Render domain objects into Telegram-ready text tables."""

from __future__ import annotations

from html import escape

from app.db.models import Deposit, FinancialGoal, Transaction
from app.services.advisor_service import RuleBreakdown
from app.services.asset_service import PositionValue, SaleResult, WealthSummary
from app.services.budget_service import BudgetAlert
from app.services.market_data import AnalystForecast
from app.services.schemas import ParsedTransaction, PeriodReport


def format_amount(value: float, currency: str) -> str:
    """Format money with a thin space thousands separator."""
    return f"{value:,.0f}".replace(",", " ") + f" {currency}"


def format_usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_signed_usd(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def format_kzt(value: float) -> str:
    sign = "-" if value < 0 else ""
    amount = f"{abs(value):,.0f}".replace(",", " ")
    return f"{sign}{amount} ₸"


def format_signed_kzt(value: float) -> str:
    amount = f"{abs(value):,.0f}".replace(",", " ")
    return f"{'+' if value >= 0 else '-'}{amount} ₸"


def format_portfolio_header(summary: WealthSummary) -> str:
    account = summary.broker_account
    if not summary.positions and account is None:
        return "💼 <b>Инвестиционный портфель</b>\nПока нет акций."
    cost = sum(item.cost_usd for item in summary.positions)
    profit = summary.portfolio_usd - cost
    icon = "🟢" if profit >= 0 else "🔴"
    lines = [
        "💼 <b>Инвестиционный портфель</b>",
        f"Чистые активы брокера: <b>{format_usd(summary.broker_total_usd)}</b> · "
        f"<b>{format_kzt(summary.broker_total_usd * summary.usd_kzt)}</b>",
        f"Акции: {format_usd(summary.portfolio_usd)} · "
        f"кэш: {format_usd(summary.broker_cash_usd)}",
        f"{icon} Нереализованный P/L: {format_signed_usd(profit)} · "
        f"{format_kzt(profit * summary.usd_kzt)}",
    ]
    if account is not None:
        realized = float(account.realized_pnl_usd)
        lines.append(f"📈 P/L закрытых сделок: <b>{format_signed_usd(realized)}</b>")
        combined_pnl = profit + realized
        combined_icon = "🟢" if combined_pnl >= 0 else "🔴"
        lines.append(
            f"{combined_icon} Общий P/L: <b>{format_signed_usd(combined_pnl)}</b> · "
            f"<b>{format_signed_kzt(combined_pnl * summary.usd_kzt)}</b>"
        )
        if account.reported_total_pnl_usd is not None:
            total_pnl = float(account.reported_total_pnl_usd)
            total_percent = float(account.reported_total_pnl_percent or 0)
            total_icon = "🟢" if total_pnl >= 0 else "🔴"
            lines.append(
                f"{total_icon} За всё время: {format_signed_usd(total_pnl)} "
                f"({total_percent:+.2f}%)"
            )
        lines.append(f"Операций: {account.transaction_count}")
    lines.append(f"Курс Yahoo: $1 = {summary.usd_kzt:,.2f} ₸")
    return "\n".join(lines)


def format_position(item: PositionValue, usd_kzt: float) -> str:
    position = item.position
    quantity = f"{float(position.quantity):,.6f}".rstrip("0").rstrip(".")
    lines = [
        f"<b>{escape(position.symbol)}</b> · {quantity} шт.",
        f"Покупка: {format_usd(float(position.average_price_usd))} за акцию",
    ]
    if item.current_price_usd is None:
        lines.append("⚠️ Текущая цена недоступна, показана себестоимость")
        lines.append(f"Себестоимость: {format_usd(item.cost_usd)}")
    else:
        icon = "🟢" if item.profit_usd >= 0 else "🔴"
        lines.extend(
            [
                f"Сейчас: {format_usd(item.current_price_usd)} за акцию",
                f"Стоимость: {format_usd(item.value_usd)} · "
                f"{format_kzt(item.value_usd * usd_kzt)}",
                f"{icon} P/L: {format_usd(item.profit_usd)} · "
                f"{format_kzt(item.profit_usd * usd_kzt)} "
                f"({item.profit_percent:+.1f}%)",
            ]
        )
    return "\n".join(lines)


def format_portfolio_forecast(
    summary: WealthSummary,
    forecasts: dict[str, AnalystForecast],
    year: int,
) -> str:
    if not forecasts:
        return ""

    lines = ["🔭 <b>Прогнозы аналитиков</b>"]
    low_value = summary.broker_cash_usd
    mean_value = summary.broker_cash_usd
    high_value = summary.broker_cash_usd

    for item in summary.positions:
        quantity = float(item.position.quantity)
        forecast = forecasts.get(item.position.symbol)
        current_value = item.value_usd
        if forecast is None:
            low_value += current_value
            mean_value += current_value
            high_value += current_value
            continue

        low_value += quantity * forecast.target_low
        mean_value += quantity * forecast.target_mean
        high_value += quantity * forecast.target_high
        current_price = item.current_price_usd
        upside = (
            (forecast.target_mean / current_price - 1) * 100
            if current_price
            else 0
        )
        analyst_text = (
            f" · аналитиков: {forecast.analyst_count}"
            if forecast.analyst_count
            else ""
        )
        lines.append(
            f"<b>{escape(forecast.symbol)}</b>: средняя цель "
            f"{format_usd(forecast.target_mean)} ({upside:+.1f}%)\n"
            f"Диапазон: {format_usd(forecast.target_low)}–"
            f"{format_usd(forecast.target_high)}{analyst_text}"
        )
        if forecast.institution_targets:
            institutions = "; ".join(
                f"{escape(target.firm)} {format_usd(target.target_price)}"
                + (f" ({escape(target.rating)})" if target.rating else "")
                for target in forecast.institution_targets
            )
            lines.append(f"Последние оценки: {institutions}")

    current = summary.broker_total_usd
    mean_change = (mean_value / current - 1) * 100 if current else 0
    lines.extend(
        [
            "",
            f"📅 <b>Возможная стоимость к концу {year}</b>",
            f"Нижний сценарий: {format_usd(low_value)} · "
            f"{format_kzt(low_value * summary.usd_kzt)}",
            f"Средний сценарий: <b>{format_usd(mean_value)}</b> · "
            f"<b>{format_kzt(mean_value * summary.usd_kzt)}</b> "
            f"({mean_change:+.1f}%)",
            f"Верхний сценарий: {format_usd(high_value)} · "
            f"{format_kzt(high_value * summary.usd_kzt)}",
            "<i>Основано на текущих 12-месячных целях Yahoo Finance; "
            "кэш учтён без изменения. Это ориентир, не гарантия.</i>",
        ]
    )
    return "\n".join(lines)


def format_portfolio(
    summary: WealthSummary,
    forecasts: dict[str, AnalystForecast] | None = None,
    forecast_year: int | None = None,
) -> str:
    """Render the entire portfolio as one compact Telegram message."""
    parts = [format_portfolio_header(summary)]
    if summary.positions:
        parts.append("📊 <b>Позиции</b>")
        parts.extend(
            format_position(item, summary.usd_kzt) for item in summary.positions
        )
    if forecasts and forecast_year:
        parts.append(format_portfolio_forecast(summary, forecasts, forecast_year))
    return "\n\n".join(parts)


def format_deposit(item: Deposit, usd_kzt: float | None = None) -> str:
    balance = float(item.balance)
    amount = format_usd(balance) if item.currency == "USD" else format_kzt(balance)
    lines = [f"🏦 <b>{escape(item.name)}</b>", f"Баланс: {amount}"]
    if usd_kzt is not None:
        converted = balance * usd_kzt if item.currency == "USD" else balance / usd_kzt
        lines.append(
            f"Эквивалент: {format_kzt(converted) if item.currency == 'USD' else format_usd(converted)}"
        )
    if item.annual_rate is not None:
        monthly_interest = balance * float(item.annual_rate) / 1200
        monthly_amount = (
            format_usd(monthly_interest)
            if item.currency == "USD"
            else format_kzt(monthly_interest)
        )
        lines.append(
            f"Ставка: {float(item.annual_rate):g}% годовых · "
            f"≈ +{monthly_amount}/мес с капитализацией"
        )
    return "\n".join(lines)


def format_deposits(items: list[Deposit]) -> str:
    """Render all deposits in one compact message."""
    if not items:
        return "🏦 <b>Депозиты</b>\nПока нет депозитов."

    total_kzt = sum(float(item.balance) for item in items if item.currency == "KZT")
    total_usd = sum(float(item.balance) for item in items if item.currency == "USD")
    totals = []
    if total_kzt:
        totals.append(format_kzt(total_kzt))
    if total_usd:
        totals.append(format_usd(total_usd))

    lines = ["🏦 <b>Депозиты</b>", f"Всего: <b>{' · '.join(totals)}</b>"]
    for item in items:
        balance = float(item.balance)
        amount = format_usd(balance) if item.currency == "USD" else format_kzt(balance)
        rate = ""
        if item.annual_rate is not None:
            monthly_interest = balance * float(item.annual_rate) / 1200
            monthly_amount = (
                format_usd(monthly_interest)
                if item.currency == "USD"
                else format_kzt(monthly_interest)
            )
            rate = (
                f" · {float(item.annual_rate):g}% годовых"
                f" · ≈ +{monthly_amount}/мес"
            )
        lines.append(f"• <b>{escape(item.name)}</b> — {amount}{rate}")
    return "\n".join(lines)


def format_goal(item: FinancialGoal, current_amount: float | None = None) -> str:
    current = (
        current_amount if current_amount is not None else float(item.current_amount)
    )
    target = float(item.target_amount)
    percent = current / target * 100 if target else 0
    filled = min(10, max(0, int(percent // 10)))
    bar = "█" * filled + "░" * (10 - filled)
    formatter = format_usd if item.currency == "USD" else format_kzt
    remaining = max(0, target - current)
    remaining_percent = max(0, 100 - percent)
    return (
        f"🎯 <b>{escape(item.title)}</b>\n"
        f"{bar} {percent:.1f}%\n"
        f"Накоплено: {formatter(current)} из {formatter(target)}\n"
        f"Осталось: {formatter(remaining)} ({remaining_percent:.1f}%)"
    )


def format_goals(items: list[FinancialGoal], summary: WealthSummary) -> str:
    """Render every goal against the user's complete current net worth."""
    if not items:
        return "🎯 <b>Финансовые цели</b>\nПока нет целей."

    parts = [
        "🎯 <b>Финансовые цели</b>",
        f"Весь капитал: <b>{format_kzt(summary.total_kzt)}</b> · "
        f"<b>{format_usd(summary.total_usd)}</b>",
    ]
    for item in items:
        current = summary.total_usd if item.currency == "USD" else summary.total_kzt
        parts.append(format_goal(item, current))
    return "\n\n".join(parts)


def format_capital(summary: WealthSummary) -> str:
    return (
        "💰 <b>Общий капитал</b>\n"
        f"<b>{format_kzt(summary.total_kzt)}</b>\n"
        f"<b>{format_usd(summary.total_usd)}</b>\n\n"
        f"Брокерский счёт: {format_usd(summary.broker_total_usd)} · "
        f"{format_kzt(summary.broker_total_usd * summary.usd_kzt)}\n"
        f"Депозиты: {format_usd(summary.deposits_kzt / summary.usd_kzt)} · "
        f"{format_kzt(summary.deposits_kzt)}\n"
        f"Курс Yahoo: $1 = {summary.usd_kzt:,.2f} ₸"
    )


def format_sale(result: SaleResult) -> str:
    sale = result.sale
    pnl = float(sale.realized_pnl_usd)
    icon = "🟢" if pnl >= 0 else "🔴"
    quantity = f"{float(sale.quantity):g}"
    return (
        f"✅ <b>{escape(sale.symbol)} продано</b>\n"
        f"{quantity} шт. по {format_usd(float(sale.sell_price_usd))}\n"
        f"Средняя цена входа: {format_usd(float(sale.average_buy_price_usd))}\n"
        f"{icon} Результат сделки: <b>{format_signed_usd(pnl)}</b>\n"
        f"P/L закрытых сделок: "
        f"<b>{format_signed_usd(float(result.account.realized_pnl_usd))}</b>\n"
        f"Осталось акций: {result.remaining_quantity:g}"
    )


def format_confirmation(parsed: ParsedTransaction, currency: str) -> str:
    kind = "Кіріс" if parsed.type.value == "income" else "Шығын"
    text = (
        f"<b>{kind}</b>\n"
        f"Сома: {format_amount(parsed.amount, currency)}\n"
        f"Санат: {parsed.category}\n"
        f"Сипаттама: {parsed.description or '—'}"
    )
    if parsed.confidence == "low":
        text += "\n\n⚠️ Сенімді емеспін — соманы мен санатты тексеріңіз."
    return text


def format_period_report(report: PeriodReport) -> str:
    """Render a :class:`PeriodReport` as a monospace text table."""
    if not report.rows:
        return f"<b>{report.title}</b>\nБұл кезеңде әзірге шығын жоқ."

    lines = [
        f"<b>{report.title}</b>",
        f"Барлығы: {format_amount(report.total, report.currency)}",
        "",
        "<pre>",
        f"{'Санат':<14}{'Сома':>12}{'%':>6}",
    ]
    for row in report.rows:
        amount = f"{row.total:,.0f}".replace(",", " ")
        lines.append(f"{row.name[:14]:<14}{amount:>12}{row.percent:>5.0f}%")
    lines.append("</pre>")
    return "\n".join(lines)


def format_budget_alert(alert: BudgetAlert, currency: str) -> str:
    icon = "🚨" if alert.level == "exceeded" else "⚠️"
    verb = "асып кетті" if alert.level == "exceeded" else "дерлік таусылды"
    return (
        f"{icon} Бюджет {verb}: <b>{alert.category_name}</b>\n"
        f"Жұмсалды {format_amount(alert.spent, currency)} "
        f"/ {format_amount(alert.limit, currency)} "
        f"({alert.ratio * 100:.0f}%)"
    )


def format_income_report(income: PeriodReport, expense_total: float) -> str:
    """Render income breakdown for the month plus the net balance."""
    currency = income.currency
    balance = income.total - expense_total
    sign = "🟢" if balance >= 0 else "🔴"

    if not income.rows:
        header = "💰 <b>Айлық кірістер</b>\nӘзірге түсім жоқ."
    else:
        lines = [
            "💰 <b>Айлық кірістер</b>",
            f"Барлығы түсті: {format_amount(income.total, currency)}",
            "",
            "<pre>",
            f"{'Дереккөз':<16}{'Сома':>12}{'%':>6}",
        ]
        for row in income.rows:
            amount = f"{row.total:,.0f}".replace(",", " ")
            lines.append(f"{row.name[:16]:<16}{amount:>12}{row.percent:>5.0f}%")
        lines.append("</pre>")
        header = "\n".join(lines)

    return (
        f"{header}\n\n"
        f"Айлық шығындар: {format_amount(expense_total, currency)}\n"
        f"{sign} Баланс: {format_amount(balance, currency)}"
    )


def _verdict(actual_pct: float, target_pct: float, lower_is_better: bool) -> str:
    diff = actual_pct - target_pct
    if lower_is_better:
        return "✅ қалыпты" if diff <= 2 else f"⚠️ мақсаттан {diff:.0f} п.т. жоғары"
    return "✅ қалыпты" if diff >= -2 else f"⚠️ мақсаттан {-diff:.0f} п.т. төмен"


def format_rule(rule: RuleBreakdown, currency: str) -> str:
    """Render the 50/30/20 breakdown, plus a realistic plan for what's left
    after fixed obligations (needs) — grounded advice, not just a % target."""
    source = "осы айда түсті" if rule.income_is_actual else "күтілетін кіріс"
    text = (
        "📊 <b>50/30/20 ережесі</b> (кіріс "
        f"{format_amount(rule.income, currency)}, {source})\n"
        f"Қажет: {format_amount(rule.needs, currency)} "
        f"({rule.needs_pct:.0f}% / мақсат 50%) — "
        f"{_verdict(rule.needs_pct, 50, lower_is_better=True)}\n"
        f"Қалаулар: {format_amount(rule.wants, currency)} "
        f"({rule.wants_pct:.0f}% / мақсат 30%) — "
        f"{_verdict(rule.wants_pct, 30, lower_is_better=True)}\n"
        f"Қалады: {format_amount(rule.savings, currency)} "
        f"({rule.savings_pct:.0f}% / мақсат 20%) — "
        f"{_verdict(rule.savings_pct, 20, lower_is_better=False)}"
    )

    remaining = rule.income - rule.needs
    if remaining > 0:
        text += (
            "\n\n💡 <b>Міндеттемелерден кейінгі саналы жоспар</b>\n"
            f"Қажеттен кейін {format_amount(remaining, currency)} қалады. "
            f"Саналысы: ~{format_amount(rule.wants_ideal, currency)} қалауларға, "
            f"~{format_amount(rule.savings_ideal, currency)} жинауға.\n"
            f"Іс жүзінде: қалауларға {format_amount(rule.wants, currency)}, "
            f"жиналғаны {format_amount(rule.savings, currency)}."
        )
    return text


def format_anomalies(anomalies: list[dict[str, object]], currency: str) -> str:
    if not anomalies:
        return "✅ Бұл айда шығынның күрт өсуі жоқ."
    lines = ["📈 <b>Шығынның әдеттен тыс өсуі</b> (орташаңа қатысты):"]
    for a in anomalies[:5]:
        cur = format_amount(float(a["current"]), currency)  # type: ignore[arg-type]
        ratio = float(a["ratio"])  # type: ignore[arg-type]
        lines.append(f"• {a['category']}: {cur} — әдеттегіден {ratio:.1f}× көп")
    return "\n".join(lines)


def format_subscriptions(subs: list[dict[str, object]], currency: str) -> str:
    if not subs:
        return "Тұрақты төлемдер таппадым (≥2 ай тарихы керек)."
    total = sum(float(s["amount"]) for s in subs)  # type: ignore[arg-type]
    lines = [f"🔁 <b>Жазылым сияқты</b> — ~{format_amount(total, currency)}/ай:"]
    for s in subs[:10]:
        amount = format_amount(float(s["amount"]), currency)  # type: ignore[arg-type]
        lines.append(f"• {s['description']}: {amount} × {s['months']} ай")
    return "\n".join(lines)


def format_benchmark(rows: list[tuple[str, float, float]]) -> str:
    """Compare user category shares vs KZ reference shares."""
    lines = [
        "🇰🇿 <b>Сен vs Қазақстан орташасы</b> (шығын үлесі, %)",
        "<pre>",
        f"{'Санат':<14}{'Сен':>6}{'ҚР':>6}",
    ]
    for name, user_pct, kz_pct in rows:
        lines.append(f"{name[:14]:<14}{user_pct:>5.0f}%{kz_pct:>5.0f}%")
    lines.append("</pre>")
    lines.append("<i>Сома емес, үлес салыстырылады — кез келген кірісте әділ.</i>")
    return "\n".join(lines)


def format_advice(advice: str) -> str:
    return f"🧠 <b>Финансовый разбор</b>\n\n{advice}"


def format_recent(transactions: list[Transaction], currency: str) -> str:
    if not transactions:
        return "Әзірге жазылған шығын жоқ."
    return "🧾 <b>Соңғы операциялар</b>\n(соманы өзгерту үшін ✏️, жою үшін 🗑 басыңыз)"


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
        "🗓 <b>Апта қорытындысы</b>",
        f"Жұмсалды: {format_amount(current, currency)}",
    ]
    if change is None:
        lines.append("Салыстыратын ештеңе жоқ — шығынмен өткен алғашқы апта.")
    else:
        change_f = float(change)
        arrow = "🔺" if change_f > 0 else ("🔻" if change_f < 0 else "▪️")
        lines.append(f"Өткен аптаға қатысты: {arrow} {abs(change_f):.0f}%")

    if top:
        lines.append("\nТоп санаттар:")
        for name, amount in list(top)[:5]:  # type: ignore[arg-type]
            lines.append(f"• {name}: {format_amount(float(amount), currency)}")
    return "\n".join(lines)
