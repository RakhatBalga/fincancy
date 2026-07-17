"""``/start`` — register the user, ask onboarding questions, show help."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    FOOD_PREFIX,
    HOUSING_PREFIX,
    food_question_keyboard,
    housing_question_keyboard,
    main_reply_keyboard,
)
from app.db.models import User
from app.services.user_service import UserService

router = Router(name="start")

_WELCOME = (
    "👋 Привет! Я помогу вести учёт личных финансов.\n\n"
    "Просто напиши трату обычным текстом, например:\n"
    "• <i>кофе 800</i>\n"
    "• <i>такси 1500</i>\n"
    "• <i>зарплата 400000</i>\n\n"
    "Команды:\n"
    "/today · /week · /month — расходы за период\n"
    "/incomes — доходы и баланс за месяц\n"
    "/chart — график расходов за месяц\n"
    "/recent — изменить или удалить траты\n"
    "/setbudget &lt;категория&gt; &lt;сумма&gt; — лимит на месяц\n"
    "/income &lt;сумма&gt; — указать доход\n"
    "/rule — правило 50/30/20\n"
    "/advice — AI-разбор месяца и советы\n"
    "/benchmark — сравнение со средним по Казахстану\n"
    "/subscriptions — найти регулярные платежи\n"
    "/reset — удалить ВСЕ траты, доходы и бюджеты"
)

_ONBOARDING_INTRO = (
    "Ещё пара вопросов — это поможет точнее считать советы "
    "(например, не придумывать тебе аренду, если ты живёшь с родителями)."
)


async def _ask_housing(message: Message) -> None:
    await message.answer(
        _ONBOARDING_INTRO + "\n\nЖильё — ты платишь за него сам(а) или бесплатно?",
        reply_markup=housing_question_keyboard(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    service = UserService(session)
    user, created = await service.register(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )

    prefix = "" if created else "С возвращением!\n\n"
    await message.answer(prefix + _WELCOME, reply_markup=main_reply_keyboard())

    if user.housing_is_free is None:
        await _ask_housing(message)
    elif user.food_is_free is None:
        # Resume: housing was answered in a prior /start but food wasn't yet.
        await message.answer(
            "А питание — в основном ешь дома бесплатно, или тратишь на еду сам(а)?",
            reply_markup=food_question_keyboard(),
        )


@router.callback_query(F.data.startswith(f"{HOUSING_PREFIX}:"))
async def on_housing_answer(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    is_free = callback.data.split(":")[1] == "1"

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выполни /start.", show_alert=True)
        return

    # Commit now (not just flush) — the food answer arrives in a *separate*
    # Telegram update with its own DB session, so this must be durable before
    # then, not just visible within the current session.
    user.housing_is_free = is_free  # type: ignore[assignment]
    await session.commit()

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "А питание — в основном ешь дома бесплатно, или тратишь на еду сам(а)?",
            reply_markup=food_question_keyboard(),
        )


@router.callback_query(F.data.startswith(f"{FOOD_PREFIX}:"))
async def on_food_answer(callback: CallbackQuery, session: AsyncSession) -> None:
    assert callback.data is not None and callback.from_user is not None
    food_is_free = callback.data.split(":")[1] == "1"

    user = await UserService(session).get(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала выполни /start.", show_alert=True)
        return

    housing_is_free = bool(user.housing_is_free)
    await UserService(session).set_living_situation(
        user, housing_is_free=housing_is_free, food_is_free=food_is_free
    )

    await callback.answer("Спасибо, учту это в советах ✅")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "Готово! Можешь писать траты обычным текстом или открыть /rule "
            "и 🧠 «Мнение ИИ» — теперь советы точнее."
        )
