"""Inline keyboards and their callback-data schema."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Persistent reply-keyboard button labels. Handlers match these exact strings.
BTN_AI = "🧠 Мнение ИИ"
BTN_TODAY = "📅 Сегодня"
BTN_MONTH = "📊 Месяц"
BTN_INCOME = "💰 Доходы"
BTN_CHART = "📈 График"

# All reply-keyboard labels — FSM "waiting for a number" states exclude these so
# a button press is never mistaken for the typed amount.
MENU_BUTTONS: frozenset[str] = frozenset(
    {BTN_AI, BTN_TODAY, BTN_MONTH, BTN_INCOME, BTN_CHART}
)

# Onboarding: housing/food cost questions asked once on first /start.
HOUSING_PREFIX = "housing"
FOOD_PREFIX = "food"


def housing_question_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🏠 Бесплатно (с родителями/семьёй)",
            callback_data=f"{HOUSING_PREFIX}:1",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💳 Плачу сам(а)", callback_data=f"{HOUSING_PREFIX}:0"
        )
    )
    return builder.as_markup()


RESET_PREFIX = "reset"


def reset_confirm_keyboard() -> InlineKeyboardMarkup:
    """Are-you-sure keyboard before wiping all of the user's data."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Да, удалить всё", callback_data=f"{RESET_PREFIX}:confirm"
        ),
        InlineKeyboardButton(
            text="Отмена", callback_data=f"{RESET_PREFIX}:cancel"
        ),
    )
    return builder.as_markup()


def food_question_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🍽 В основном бесплатно (дома)", callback_data=f"{FOOD_PREFIX}:1"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💳 Плачу сам(а)/трачу на еду", callback_data=f"{FOOD_PREFIX}:0"
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
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши трату, напр. «кофе 800»",
    )

from app.db.models import Category

# Callback data format: "confirm:<transaction_id>" / "recat:<transaction_id>"
# and for the category picker: "setcat:<transaction_id>:<category_id>".
CONFIRM_PREFIX = "confirm"
RECAT_PREFIX = "recat"
SETCAT_PREFIX = "setcat"
TXDEL_PREFIX = "txdel"
TXEDIT_PREFIX = "txedit"


def confirm_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Confirm / change-category / delete keyboard after a parsed transaction."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Ок",
            callback_data=f"{CONFIRM_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="✏️ Категория",
            callback_data=f"{RECAT_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"{TXDEL_PREFIX}:{transaction_id}",
        ),
    )
    return builder.as_markup()


def category_picker_keyboard(
    transaction_id: int, categories: list[Category]
) -> InlineKeyboardMarkup:
    """Grid of the user's categories for reassigning a transaction."""
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=category.name,
            callback_data=f"{SETCAT_PREFIX}:{transaction_id}:{category.id}",
        )
    builder.adjust(2)
    return builder.as_markup()


def transaction_row_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    """Edit-amount / delete buttons shown under each recent transaction."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ Сумма",
            callback_data=f"{TXEDIT_PREFIX}:{transaction_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"{TXDEL_PREFIX}:{transaction_id}",
        ),
    )
    return builder.as_markup()
