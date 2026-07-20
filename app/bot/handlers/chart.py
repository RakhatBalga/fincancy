"""``/chart`` — send the current month's spending as a pie image."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.charts import pie_chart
from app.bot.keyboards import CHART_BUTTONS
from app.services.analytics_service import AnalyticsService
from app.services.user_service import UserService

router = Router(name="chart")


@router.message(Command("chart"))
@router.message(F.text.in_(CHART_BUTTONS))
async def cmd_chart(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await UserService(session).get(message.from_user.id)
    if user is None:
        await message.answer("Алдымен /start басыңыз.")
        return

    report = await AnalyticsService(session).month(user)
    image = pie_chart(report)
    if image is None:
        await message.answer("Айда шығын жоқ — диаграмма құруға дерек жоқ.")
        return

    await message.answer_photo(
        BufferedInputFile(image, filename="chart.png"),
        caption=f"Айлық шығындар: {report.total:,.0f} {report.currency}".replace(
            ",", " "
        ),
    )
