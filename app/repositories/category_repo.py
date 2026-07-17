"""Data access for :class:`Category`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category

# Full category taxonomy (matches the Gemini parser prompt) → 50/30/20 bucket.
# "needs" = essentials, "wants" = discretionary, "savings" = money set aside
# (excluded from BOTH needs and wants so it doesn't distort either share).
# Income categories map to None (excluded from the needs/wants/savings math,
# which counts expenses only).
CATEGORY_GROUPS: dict[str, str | None] = {
    "продукты": "needs",
    "еда вне дома": "wants",
    "транспорт": "needs",
    "такси": "wants",
    "жильё": "needs",
    "коммуналка": "needs",
    "связь и интернет": "needs",
    "здоровье": "needs",
    "одежда": "wants",
    "развлечения": "wants",
    "подписки": "wants",
    "образование": "needs",
    "детям": "needs",
    "подарки": "wants",
    "путешествия": "wants",
    # Contractual/family obligations count as needs, not discretionary wants.
    "кредиты и рассрочка": "needs",
    "помощь семье": "needs",
    "переводы": "wants",
    "прочее": "wants",
    # Money moved into savings/investments — not a "want", shouldn't inflate it.
    "депозит": "savings",
    "накопления": "savings",
    "сбережения": "savings",
    "вклад": "savings",
    "инвестиции": "savings",
    "зарплата": None,
    "доход прочее": None,
}

# Substring keywords for auto-created categories not in the taxonomy above
# (e.g. user types "мой депозит" or "накопления на авто").
_SAVINGS_KEYWORDS: tuple[str, ...] = (
    "депозит",
    "накоплени",
    "сбережен",
    "вклад",
    "инвестици",
)

# Categories pre-created on /start. A curated core subset — the rest are
# created on demand when the parser first returns them.
DEFAULT_CATEGORIES: tuple[str, ...] = (
    "продукты",
    "еда вне дома",
    "транспорт",
    "такси",
    "жильё",
    "коммуналка",
    "связь и интернет",
    "здоровье",
    "развлечения",
    "прочее",
)


def group_for(name: str) -> str | None:
    """Return the 50/30/20 bucket for a category name (defaults to wants)."""
    key = name.strip().casefold()
    if key in CATEGORY_GROUPS:
        return CATEGORY_GROUPS[key]
    if any(kw in key for kw in _SAVINGS_KEYWORDS):
        return "savings"
    return "wants"


class CategoryRepository:
    """CRUD operations for categories."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_defaults(self, user_id: int) -> list[Category]:
        """Create the default category set for a freshly-registered user."""
        categories = [
            Category(
                user_id=user_id,
                name=name,
                is_default=True,
                group_type=group_for(name),
            )
            for name in DEFAULT_CATEGORIES
        ]
        self._session.add_all(categories)
        await self._session.flush()
        return categories

    async def list_for_user(self, user_id: int) -> list[Category]:
        result = await self._session.execute(
            select(Category).where(Category.user_id == user_id).order_by(Category.id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, category_id: int, user_id: int) -> Category | None:
        result = await self._session.execute(
            select(Category).where(
                Category.id == category_id, Category.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, user_id: int, name: str) -> Category | None:
        """Case-insensitive lookup of a category by name.

        Matching is done in Python with ``casefold`` rather than SQL
        ``lower()`` — SQLite's ``lower()`` does not fold non-ASCII (Cyrillic)
        letters, which would silently break lookups and create duplicates.
        A user has only a handful of categories, so loading them is cheap.
        """
        target = name.strip().casefold()
        for category in await self.list_for_user(user_id):
            if category.name.casefold() == target:
                return category
        return None

    async def get_or_create(self, user_id: int, name: str) -> Category:
        """Return an existing category by name or create a custom one.

        The 50/30/20 bucket is derived from the taxonomy map (unknown names
        fall back to "wants"), so auto-created categories are grouped too.
        """
        existing = await self.get_by_name(user_id, name)
        if existing is not None:
            return existing
        category = Category(
            user_id=user_id,
            name=name,
            is_default=False,
            group_type=group_for(name),
        )
        self._session.add(category)
        await self._session.flush()
        return category
