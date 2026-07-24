"""AI advice and rule-based coaching: /advice, /rule, /benchmark."""

from __future__ import annotations

import html
import re

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import (
    format_advice,
    format_benchmark,
    format_rule,
)
from app.bot.keyboards import (
    ADVICE_PERIOD_PREFIX,
    ADVICE_PERIODS,
    AI_BUTTONS,
    advice_period_keyboard,
)
from app.db.models import User
from app.services.advisor_service import (
    AdvicePeriod,
    AdvisorService,
    build_asset_advice_summary,
)
from app.services.analytics_service import AnalyticsService
from app.services.asset_service import AssetService
from app.services.installment_schedule import installment_schedule_summary
from app.services.market_data import MarketDataError, YahooFinanceService
from app.services.user_service import UserService

router = Router(name="advice")
log = structlog.get_logger(__name__)

_RISK_LEVELS = {
    "низкий": "низкий",
    "низкая": "низкий",
    "low": "низкий",
    "средний": "средний",
    "средняя": "средний",
    "medium": "средний",
    "высокий": "высокий",
    "высокая": "высокий",
    "high": "высокий",
}
_OBLIGATION_TYPES = {
    "кредит": "кредиты",
    "кредиты": "кредиты",
    "рассрочка": "рассрочки",
    "рассрочки": "рассрочки",
}


def _optional_number(raw: str) -> float | None:
    value = raw.strip()
    if value in {"", "-", "нет", "не знаю"}:
        return None
    return float(value.replace(" ", "").replace(",", "."))


def _profile_input(
    raw: str,
) -> tuple[int, float | None, float | None, str | None, str | None]:
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) not in {1, 4, 5}:
        raise ValueError
    age = int(parts[0])
    if len(parts) == 1:
        return age, None, None, None, None
    debt_balance = _optional_number(parts[1])
    debt_rate = _optional_number(parts[2])
    risk_raw = parts[3].casefold()
    risk = None if risk_raw in {"", "-", "не знаю"} else _RISK_LEVELS.get(risk_raw)
    if risk_raw not in {"", "-", "не знаю"} and risk is None:
        raise ValueError
    obligation = None
    if len(parts) == 5:
        obligation_raw = parts[4].casefold()
        obligation = (
            None
            if obligation_raw in {"", "-", "не знаю"}
            else _OBLIGATION_TYPES.get(obligation_raw)
        )
        if obligation_raw not in {"", "-", "не знаю"} and obligation is None:
            raise ValueError
    return age, debt_balance, debt_rate, risk, obligation


def _profile_text(user: User) -> str:
    debt = (
        f"{float(user.debt_balance):,.0f} ₸".replace(",", " ")
        if user.debt_balance is not None
        else "не указан"
    )
    rate = (
        f"{float(user.debt_annual_rate):g}%"
        if user.debt_annual_rate is not None
        else "не указана"
    )
    salary = float(user.official_salary_monthly or 0)
    stipend = float(user.official_stipend_monthly or 0)
    official_income = salary + stipend
    payment_limit = (
        official_income * float(user.mortgage_payment_limit_percent) / 100
        if official_income and user.mortgage_payment_limit_percent is not None
        else 0
    )
    installment_total = float(user.installment_balance_primary or 0) + float(
        user.installment_balance_secondary or 0
    )
    official_line = "Официальный доход: не указан"
    if official_income:
        official_line = (
            f"Официальный доход: {official_income:,.0f} ₸"
            f" ({salary:,.0f} ₸ зарплата + {stipend:,.0f} ₸ стипендия)"
        ).replace(",", " ")
    limit_line = "Лимит ипотечного платежа: не указан"
    if payment_limit:
        limit_line = (
            f"Лимит ипотечного платежа: {payment_limit:,.0f} ₸ "
            f"({float(user.mortgage_payment_limit_percent):g}%)"
        ).replace(",", " ")
    installment_line = ""
    if installment_total and user.installment_end_date:
        installment_line = (
            f"Остаток рассрочек: {installment_total:,.0f} ₸ · до "
            f"{user.installment_end_date.strftime('%m.%Y')}"
        ).replace(",", " ")
    lines = [
        "👤 <b>Финансовый профиль</b>",
        f"Возраст: {user.age or 'не указан'}",
        f"Остаток долгов: {debt}",
        f"Максимальная ставка: {rate}",
        f"Тип обязательств: {user.obligation_type or 'не указан'}",
        f"Отношение к риску: {user.risk_tolerance or 'не указано'}",
        "",
        official_line,
        limit_line,
    ]
    if installment_line:
        lines.append(installment_line)
    combined_schedule = installment_schedule_summary(user, combined=True)
    if combined_schedule:
        lines.append(f"Общий график платежей: {combined_schedule}")
    lines.extend(
        [
            "",
            "Обновить: "
            "<code>/profile 21 | 3500000 | 19.5 | средний | рассрочки</code>",
            "Неизвестное значение можно заменить на <code>-</code>.",
        ]
    )
    return "\n".join(lines)


async def _require_user(message: Message, session: AsyncSession) -> User | None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Алдымен /start басыңыз.")
    return user


@router.message(Command("profile"))
async def cmd_profile(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
) -> None:
    user = await _require_user(message, session)
    if user is None:
        return
    if not command.args:
        await message.answer(_profile_text(user))
        return
    try:
        age, debt_balance, debt_rate, risk, obligation = _profile_input(command.args)
        if "|" not in command.args:
            debt_balance = (
                float(user.debt_balance) if user.debt_balance is not None else None
            )
            debt_rate = (
                float(user.debt_annual_rate)
                if user.debt_annual_rate is not None
                else None
            )
            risk = user.risk_tolerance
            obligation = user.obligation_type
        await UserService(session).set_financial_profile(
            user,
            age=age,
            debt_balance=debt_balance,
            debt_annual_rate=debt_rate,
            risk_tolerance=risk,
            obligation_type=obligation,
        )
    except ValueError:
        await message.answer(
            "Формат: "
            "<code>/profile 21 | 3500000 | 19.5 | средний | рассрочки</code>\n"
            "Риск: низкий, средний или высокий. Тип: кредиты или рассрочки. "
            "Неизвестное значение: <code>-</code>."
        )
        return
    await message.answer("✅ Профиль сохранён.\n\n" + _profile_text(user))


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


@router.message(F.text.in_(AI_BUTTONS))
async def show_advice_menu(message: Message) -> None:
    await message.answer(
        "За какой период дать финансовое мнение?",
        reply_markup=advice_period_keyboard(),
    )


@router.message(Command("advice"))
async def cmd_advice(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    raw_period = (command.args or "").strip().casefold()
    aliases = {
        "today": AdvicePeriod.today,
        "сегодня": AdvicePeriod.today,
        "week": AdvicePeriod.week,
        "неделя": AdvicePeriod.week,
        "month": AdvicePeriod.month,
        "месяц": AdvicePeriod.month,
        "overall": AdvicePeriod.overall,
        "в целом": AdvicePeriod.overall,
    }
    if not raw_period:
        await show_advice_menu(message)
        return
    period = aliases.get(raw_period)
    if period is None:
        await message.answer(
            "Период не распознан. Используйте: "
            "<code>/advice today</code>, <code>week</code>, "
            "<code>month</code> или <code>overall</code>."
        )
        return
    await _run_advice(message, session, market, period)


@router.callback_query(F.data.startswith(f"{ADVICE_PERIOD_PREFIX}:"))
async def choose_advice_period(
    callback: CallbackQuery,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    assert callback.data is not None
    raw_period = callback.data.split(":", 1)[1]
    if raw_period not in ADVICE_PERIODS:
        await callback.answer("Неизвестный период.", show_alert=True)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await _run_advice(
            callback.message,
            session,
            market,
            AdvicePeriod(raw_period),
            telegram_id=callback.from_user.id,
        )


async def _run_advice(
    message: Message,
    session: AsyncSession,
    market: YahooFinanceService,
    period: AdvicePeriod,
    *,
    telegram_id: int | None = None,
) -> None:
    user = (
        await _require_user(message, session)
        if telegram_id is None
        else await UserService(session).get(telegram_id)
    )
    if user is None:
        if telegram_id is not None:
            await message.answer("Алдымен /start басыңыз.")
        return

    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, "typing")

    advisor = AdvisorService(session)
    asset_context = None
    if period in {AdvicePeriod.month, AdvicePeriod.overall}:
        try:
            asset_service = AssetService(session, market)
            wealth = await asset_service.wealth(user.id)
            goals = await asset_service.goals(user.id)
            asset_context = build_asset_advice_summary(wealth, goals)
        except MarketDataError:
            log.warning("asset_quotes_unavailable_for_advice", user_id=user.id)

    try:
        advice = await advisor.period_advice(user, period, asset_context)
    except Exception:  # noqa: BLE001 - keep the bot responsive on AI failures
        log.exception(
            "period_advice_failed",
            user_id=user.id,
            period=period.value,
        )
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
