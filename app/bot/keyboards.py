"""Inline keyboards and their callback-data schema."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import Category

# Persistent reply-keyboard button labels. Handlers match these exact strings.
BTN_AI = "🧠 ЖИ пікірі"
BTN_TODAY = "📅 Бүгін"
BTN_MONTH = "📊 Ай"
BTN_INCOME = "💰 Кірістер"
BTN_CHART = "📈 Диаграмма"
BTN_PORTFOLIO = "💼 Портфель"
BTN_DEPOSITS = "🏦 Депозиты"
BTN_FIN_GOALS = "🎯 Финцели"
BTN_CAPITAL = "💰 Капитал"

# Legacy Russian labels: Telegram caches the reply keyboard per chat, so users
# who haven't re-run /start since the Kazakh switch still send the old text.
# Handlers accept both, otherwise those taps fall through to the free-text
# parser and get treated as an expense.
_LEGACY_AI = "🧠 Мнение ИИ"
_LEGACY_TODAY = "📅 Сегодня"
_LEGACY_MONTH = "📊 Месяц"
_LEGACY_INCOME = "💰 Доходы"
_LEGACY_CHART = "📈 График"

AI_BUTTONS: frozenset[str] = frozenset({BTN_AI, _LEGACY_AI})
TODAY_BUTTONS: frozenset[str] = frozenset({BTN_TODAY, _LEGACY_TODAY})
MONTH_BUTTONS: frozenset[str] = frozenset({BTN_MONTH, _LEGACY_MONTH})
INCOME_BUTTONS: frozenset[str] = frozenset({BTN_INCOME, _LEGACY_INCOME})
CHART_BUTTONS: frozenset[str] = frozenset({BTN_CHART, _LEGACY_CHART})
PORTFOLIO_BUTTONS: frozenset[str] = frozenset({BTN_PORTFOLIO})
DEPOSIT_BUTTONS: frozenset[str] = frozenset({BTN_DEPOSITS})
FIN_GOAL_BUTTONS: frozenset[str] = frozenset({BTN_FIN_GOALS})
CAPITAL_BUTTONS: frozenset[str] = frozenset({BTN_CAPITAL})

# All reply-keyboard labels — FSM "waiting for a number" states exclude these so
# a button press is never mistaken for the typed amount.
MENU_BUTTONS: frozenset[str] = (
    AI_BUTTONS
    | TODAY_BUTTONS
    | MONTH_BUTTONS
    | INCOME_BUTTONS
    | CHART_BUTTONS
    | PORTFOLIO_BUTTONS
    | DEPOSIT_BUTTONS
    | FIN_GOAL_BUTTONS
    | CAPITAL_BUTTONS
)

# Onboarding: housing/food cost questions asked once on first /start.
HOUSING_PREFIX = "housing"
FOOD_PREFIX = "food"


def housing_question_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🏠 Тегін (ата-анамен/отбасымен)",
            callback_data=f"{HOUSING_PREFIX}:1",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💳 Өзім төлеймін", callback_data=f"{HOUSING_PREFIX}:0"
        )
    )
    return builder.as_markup()


RESET_PREFIX = "reset"


def reset_confirm_keyboard() -> InlineKeyboardMarkup:
    """Are-you-sure keyboard before wiping all of the user's data."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Иә, барлығын жою", callback_data=f"{RESET_PREFIX}:confirm"
        ),
        InlineKeyboardButton(text="Болдырмау", callback_data=f"{RESET_PREFIX}:cancel"),
    )
    return builder.as_markup()


def food_question_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🍽 Негізінен тегін (үйде)", callback_data=f"{FOOD_PREFIX}:1"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💳 Тамаққа өзім жұмсаймын", callback_data=f"{FOOD_PREFIX}:0"
        )
    )
    return builder.as_markup()


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Always-visible keyboard with the AI-opinion button and quick reports."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_AI)],
            [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_MONTH)],
            [KeyboardButton(text=BTN_INCOME), KeyboardButton(text=BTN_CHART)],
            [KeyboardButton(text=BTN_PORTFOLIO), KeyboardButton(text=BTN_DEPOSITS)],
            [KeyboardButton(text=BTN_FIN_GOALS), KeyboardButton(text=BTN_CAPITAL)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Шығын жаз, мыс. «кофе 800»",
    )


# Callback data format: "confirm:<transaction_id>" / "recat:<transaction_id>"
# and for the category picker: "setcat:<transaction_id>:<category_id>".
CONFIRM_PREFIX = "confirm"
RECAT_PREFIX = "recat"
SETCAT_PREFIX = "setcat"
TXDEL_PREFIX = "txdel"
TXEDIT_PREFIX = "txedit"
CUSTOM_CAT_PREFIX = "custcat"


def confirm_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Confirm / change-category / delete keyboard after a parsed transaction."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Жарайды",
            callback_data=f"{CONFIRM_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="✏️ Санат",
            callback_data=f"{RECAT_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Жою",
            callback_data=f"{TXDEL_PREFIX}:{transaction_id}",
        ),
    )
    return builder.as_markup()


def category_picker_keyboard(
    transaction_id: int, categories: list[Category]
) -> InlineKeyboardMarkup:
    """Grid of the user's categories for reassigning a transaction.

    Always ends with a "type your own" option, since the wanted category may
    not exist yet (e.g. it was never used by the free-text parser before).
    """
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=category.name,
            callback_data=f"{SETCAT_PREFIX}:{transaction_id}:{category.id}",
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(
            text="✏️ Өз санатым",
            callback_data=f"{CUSTOM_CAT_PREFIX}:{transaction_id}",
        )
    )
    return builder.as_markup()


def transaction_row_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Edit-amount / change-category / delete buttons under a recent transaction."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ Сома",
            callback_data=f"{TXEDIT_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="🏷 Санат",
            callback_data=f"{RECAT_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Жою",
            callback_data=f"{TXDEL_PREFIX}:{transaction_id}",
        ),
    )
    return builder.as_markup()


ASSET_ADD_POSITION = "asset:add_position"
ASSET_SELL_POSITION = "asset:sell_position"
ASSET_ADD_DEPOSIT = "asset:add_deposit"
ASSET_ADD_GOAL = "asset:add_goal"
ASSET_DELETE_PREFIX = "assetdel"
ASSET_GOAL_UPDATE_PREFIX = "goalupd"
ASSET_DEPOSIT_UPDATE_PREFIX = "depupd"


def portfolio_actions_keyboard(
    positions: list[tuple[int, str]] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить акцию", callback_data=ASSET_ADD_POSITION
        ),
        InlineKeyboardButton(text="💵 Продать", callback_data=ASSET_SELL_POSITION),
    )
    delete_buttons = [
        InlineKeyboardButton(
            text=f"🗑 {symbol}",
            callback_data=f"{ASSET_DELETE_PREFIX}:position:{item_id}",
        )
        for item_id, symbol in positions or []
    ]
    for index in range(0, len(delete_buttons), 2):
        builder.row(*delete_buttons[index : index + 2])
    return builder.as_markup()


def deposit_actions_keyboard(
    deposits: list[tuple[int, str]] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить депозит", callback_data=ASSET_ADD_DEPOSIT
        )
    )
    for item_id, name in deposits or []:
        label = name[:18]
        builder.row(
            InlineKeyboardButton(
                text=f"✏️ {label}",
                callback_data=f"{ASSET_DEPOSIT_UPDATE_PREFIX}:{item_id}",
            ),
            InlineKeyboardButton(
                text=f"🗑 {label}",
                callback_data=f"{ASSET_DELETE_PREFIX}:deposit:{item_id}",
            ),
        )
    return builder.as_markup()


def goal_actions_keyboard(
    goals: list[tuple[int, str]] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить цель", callback_data=ASSET_ADD_GOAL)
    )
    delete_buttons = [
        InlineKeyboardButton(
            text=f"🗑 {title[:18]}",
            callback_data=f"{ASSET_DELETE_PREFIX}:goal:{goal_id}",
        )
        for goal_id, title in goals or []
    ]
    for index in range(0, len(delete_buttons), 2):
        builder.row(*delete_buttons[index : index + 2])
    return builder.as_markup()


def asset_delete_keyboard(kind: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"{ASSET_DELETE_PREFIX}:{kind}:{item_id}",
                )
            ]
        ]
    )


def deposit_item_keyboard(deposit_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Обновить баланс",
                    callback_data=f"{ASSET_DEPOSIT_UPDATE_PREFIX}:{deposit_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"{ASSET_DELETE_PREFIX}:deposit:{deposit_id}",
                ),
            ]
        ]
    )


def goal_item_keyboard(goal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Обновить накопления",
                    callback_data=f"{ASSET_GOAL_UPDATE_PREFIX}:{goal_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"{ASSET_DELETE_PREFIX}:goal:{goal_id}",
                ),
            ]
        ]
    )
