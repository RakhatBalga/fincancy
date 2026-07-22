"""Portfolio, deposits, financial goals, and total capital UI."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatters import (
    format_capital,
    format_deposits,
    format_goals,
    format_portfolio,
    format_sale,
)
from app.bot.keyboards import (
    ASSET_ADD_DEPOSIT,
    ASSET_ADD_GOAL,
    ASSET_ADD_POSITION,
    ASSET_DELETE_PREFIX,
    ASSET_DEPOSIT_UPDATE_PREFIX,
    ASSET_GOAL_UPDATE_PREFIX,
    ASSET_SELL_POSITION,
    CAPITAL_BUTTONS,
    DEPOSIT_BUTTONS,
    FIN_GOAL_BUTTONS,
    MENU_BUTTONS,
    PORTFOLIO_BUTTONS,
    deposit_actions_keyboard,
    goal_actions_keyboard,
    portfolio_actions_keyboard,
)
from app.services.asset_service import AssetService
from app.services.market_data import MarketDataError, YahooFinanceService
from app.services.user_service import UserService

router = Router(name="assets")


class AssetInput(StatesGroup):
    position = State()
    sale = State()
    deposit = State()
    goal = State()
    goal_amount = State()
    deposit_amount = State()


def _number(raw: str) -> float:
    return float(raw.strip().replace(" ", "").replace(",", "."))


def _money(raw: str, default_currency: str = "KZT") -> tuple[float, str, bool]:
    match = re.fullmatch(
        r"\s*([\d\s]+(?:[.,]\d+)?)\s*(KZT|USD|₸|\$)?\s*",
        raw,
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError("invalid money")
    token = (match.group(2) or default_currency).upper()
    currency = "KZT" if token == "₸" else "USD" if token == "$" else token
    return _number(match.group(1)), currency, match.group(2) is not None


def _goal_input(text: str) -> tuple[str, float, float, str]:
    """Accept both ``квартира 30000000`` and the detailed pipe format."""
    if "|" not in text:
        match = re.fullmatch(
            r"\s*(?P<title>[^|\d]+?)\s+"
            r"(?P<amount>\d[\d\s]*(?:[.,]\d+)?)\s*"
            r"(?P<currency>KZT|USD|₸|\$)?\s*",
            text,
            re.IGNORECASE,
        )
        if match is None:
            raise ValueError("invalid simple goal")
        amount_text = match.group("amount")
        if match.group("currency"):
            amount_text += f" {match.group('currency')}"
        target, currency, _ = _money(amount_text)
        return match.group("title").strip(), target, 0, currency

    parts = [part.strip() for part in text.split("|")]
    if len(parts) not in {2, 3} or not parts[0]:
        raise ValueError("invalid detailed goal")
    target, target_currency, target_explicit = _money(parts[1])
    if len(parts) == 3:
        current, current_currency, current_explicit = _money(parts[2], target_currency)
    else:
        current, current_currency, current_explicit = 0, target_currency, False
    currency = current_currency if current_explicit else target_currency
    if target_explicit and current_explicit and target_currency != current_currency:
        raise ValueError("goal currencies do not match")
    return parts[0], target, current, currency


async def _user(message: Message, session: AsyncSession):
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажмите /start.")
    return user


async def _callback_user(callback: CallbackQuery, session: AsyncSession):
    assert callback.from_user is not None
    return await UserService(session).get(callback.from_user.id)


@router.message(Command("portfolio"))
@router.message(F.text.in_(PORTFOLIO_BUTTONS))
async def show_portfolio(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    await state.clear()
    user = await _user(message, session)
    if user is None:
        return
    if message.bot is not None:
        await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        summary = await AssetService(session, market).wealth(user.id)
    except MarketDataError:
        await message.answer("Yahoo Finance сейчас недоступен. Попробуйте чуть позже.")
        return
    try:
        forecasts = await market.forecasts(
            [item.position.symbol for item in summary.positions]
        )
    except MarketDataError:
        forecasts = {}
    await message.answer(
        format_portfolio(
            summary,
            forecasts,
            datetime.now(ZoneInfo(user.timezone)).year,
        ),
        reply_markup=portfolio_actions_keyboard(
            [(item.position.id, item.position.symbol) for item in summary.positions]
        ),
    )


@router.message(Command("deposits"))
@router.message(F.text.in_(DEPOSIT_BUTTONS))
async def show_deposits(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    user = await _user(message, session)
    if user is None:
        return
    items = await AssetService(session).deposits(user.id)
    await message.answer(
        format_deposits(items),
        reply_markup=deposit_actions_keyboard([(item.id, item.name) for item in items]),
    )


@router.message(Command("fingoals"))
@router.message(F.text.in_(FIN_GOAL_BUTTONS))
async def show_goals(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    await state.clear()
    user = await _user(message, session)
    if user is None:
        return
    service = AssetService(session, market)
    items = await service.goals(user.id)
    try:
        summary = await service.wealth(user.id)
    except MarketDataError:
        await message.answer(
            "Не удалось получить котировки для расчёта общего капитала."
        )
        return
    await message.answer(
        format_goals(items, summary),
        reply_markup=goal_actions_keyboard([(item.id, item.title) for item in items]),
    )


@router.message(Command("capital"))
@router.message(F.text.in_(CAPITAL_BUTTONS))
async def show_capital(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    await state.clear()
    user = await _user(message, session)
    if user is None:
        return
    try:
        summary = await AssetService(session, market).wealth(user.id)
    except MarketDataError:
        await message.answer("Не удалось получить курс USD/KZT от Yahoo Finance.")
        return
    await message.answer(format_capital(summary))


@router.callback_query(F.data == ASSET_ADD_POSITION)
async def add_position_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AssetInput.position)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введите тикер, количество акций и среднюю цену покупки в USD:\n"
            "<code>AAPL 10 180</code>"
        )


@router.message(
    StateFilter(AssetInput.position),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def add_position_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    market: YahooFinanceService,
) -> None:
    assert message.text is not None
    parts = message.text.split()
    try:
        if len(parts) != 3 or not re.fullmatch(r"[A-Za-z0-9.^=-]{1,24}", parts[0]):
            raise ValueError
        symbol = parts[0].upper()
        quantity = _number(parts[1])
        average_price = _number(parts[2])
        quote = await market.quote(symbol)
        if quote.currency != "USD":
            raise ValueError
    except (ValueError, MarketDataError):
        await message.answer(
            "Не получилось проверить акцию. Формат: <code>AAPL 10 180</code>. "
            "Поддерживаются бумаги с котировкой в USD."
        )
        return
    user = await _user(message, session)
    if user is None:
        return
    await AssetService(session, market).add_position(
        user.id, symbol, quantity, average_price
    )
    await state.clear()
    await message.answer(
        f"✅ {symbol}: {quantity:g} шт. по ${average_price:,.2f} сохранено. "
        f"Текущая цена Yahoo: ${quote.price:,.2f}."
    )


@router.callback_query(F.data == ASSET_SELL_POSITION)
async def sell_position_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AssetInput.sale)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введите тикер, количество и фактическую цену продажи в USD:\n"
            "<code>APLD 5 35</code>"
        )


@router.message(
    StateFilter(AssetInput.sale),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def sell_position_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.text is not None
    user = await _user(message, session)
    if user is None:
        return
    parts = message.text.split()
    try:
        if len(parts) != 3 or not re.fullmatch(r"[A-Za-z0-9.^=-]{1,24}", parts[0]):
            raise ValueError("неверный формат")
        result = await AssetService(session).sell_position(
            user_id=user.id,
            symbol=parts[0],
            quantity=_number(parts[1]),
            sell_price_usd=_number(parts[2]),
        )
    except ValueError as exc:
        await message.answer(
            "Не удалось записать продажу. Проверьте тикер, количество и цену. "
            f"Формат: <code>APLD 5 35</code>. ({exc})"
        )
        return
    await state.clear()
    await message.answer(format_sale(result))


@router.callback_query(F.data == ASSET_ADD_DEPOSIT)
async def add_deposit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AssetInput.deposit)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введите название, баланс и при желании годовую ставку:\n"
            "<code>Kaspi | 2500000 KZT | 15</code>"
        )


@router.message(
    StateFilter(AssetInput.deposit),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def add_deposit_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.text is not None
    parts = [part.strip() for part in message.text.split("|")]
    try:
        if len(parts) not in {2, 3} or not parts[0]:
            raise ValueError
        balance, currency, _ = _money(parts[1])
        annual_rate = _number(parts[2].rstrip("%")) if len(parts) == 3 else None
    except ValueError:
        await message.answer("Формат: <code>Kaspi | 2500000 KZT | 15</code>")
        return
    user = await _user(message, session)
    if user is None:
        return
    await AssetService(session).add_deposit(
        user.id, parts[0], balance, currency, annual_rate
    )
    await state.clear()
    await message.answer("✅ Депозит сохранён.")


@router.callback_query(F.data == ASSET_ADD_GOAL)
async def add_goal_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AssetInput.goal)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Введите цель и нужную сумму:\n"
            "<code>квартира 30000000</code>\n\n"
            "Если уже есть накопления:\n"
            "<code>MacBook | 1500000 | 300000 KZT</code>"
        )


@router.message(
    StateFilter(AssetInput.goal),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def add_goal_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.text is not None
    try:
        title, target, current, currency = _goal_input(message.text)
    except ValueError:
        await message.answer("Напишите, например: <code>квартира 30000000</code>")
        return
    user = await _user(message, session)
    if user is None:
        return
    await AssetService(session).add_goal(user.id, title, target, current, currency)
    await state.clear()
    await message.answer("✅ Финансовая цель сохранена.")


@router.callback_query(F.data.startswith(f"{ASSET_GOAL_UPDATE_PREFIX}:"))
async def update_goal_start(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    await state.set_state(AssetInput.goal_amount)
    await state.update_data(goal_id=int(callback.data.split(":")[1]))
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Введите новую накопленную сумму:")


@router.message(
    StateFilter(AssetInput.goal_amount),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def update_goal_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.text is not None
    try:
        amount = _money(message.text)[0]
    except ValueError:
        await message.answer("Введите сумму числом, например <code>450000</code>.")
        return
    data = await state.get_data()
    user = await _user(message, session)
    if user is None:
        return
    goal = await AssetService(session).update_goal_amount(
        user.id, int(data["goal_id"]), amount
    )
    await state.clear()
    await message.answer(
        "✅ Накопленная сумма обновлена." if goal else "Цель не найдена."
    )


@router.callback_query(F.data.startswith(f"{ASSET_DEPOSIT_UPDATE_PREFIX}:"))
async def update_deposit_start(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    await state.set_state(AssetInput.deposit_amount)
    await state.update_data(deposit_id=int(callback.data.split(":")[1]))
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Введите новый баланс депозита:")


@router.message(
    StateFilter(AssetInput.deposit_amount),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_BUTTONS),
)
async def update_deposit_finish(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    assert message.text is not None
    try:
        amount = _money(message.text)[0]
    except ValueError:
        await message.answer("Введите сумму числом, например <code>2750000</code>.")
        return
    data = await state.get_data()
    user = await _user(message, session)
    if user is None:
        return
    deposit = await AssetService(session).update_deposit_balance(
        user.id, int(data["deposit_id"]), amount
    )
    await state.clear()
    await message.answer("✅ Баланс обновлён." if deposit else "Депозит не найден.")


@router.callback_query(F.data.startswith(f"{ASSET_DELETE_PREFIX}:"))
async def delete_asset(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None
    _, kind, raw_id = callback.data.split(":")
    user = await _callback_user(callback, session)
    if user is None:
        await callback.answer("Сначала нажмите /start.", show_alert=True)
        return
    service = AssetService(session)
    methods = {
        "position": service.delete_position,
        "deposit": service.delete_deposit,
        "goal": service.delete_goal,
    }
    method = methods.get(kind)
    deleted = await method(user.id, int(raw_id)) if method else False
    await callback.answer(
        "Удалено" if deleted else "Не удалось удалить", show_alert=not deleted
    )
    if deleted and isinstance(callback.message, Message):
        await callback.message.edit_text("<s>Удалено</s>")
