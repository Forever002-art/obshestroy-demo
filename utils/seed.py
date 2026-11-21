"""Начальные данные: категории и подкатегории каталога."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Category, Company, SubCategory
from utils.catalog_data import (CATEGORIES, DEFAULT_SETTINGS, MATERIAL_SUBCATEGORIES, MATERIALS_TITLE,  # noqa: F401
                                REMOVED_CATEGORIES)


async def seed_categories(session: AsyncSession) -> None:
    """Идемпотентно добавляет категории и подкатегории, убирает устаревшие."""
    await session.execute(delete(Category).where(Category.title.in_(REMOVED_CATEGORIES),
                                                 Category.id.not_in(select(Company.category_id))))
    existing = {c.title: c for c in (await session.scalars(select(Category))).all()}
    for order, title in enumerate(CATEGORIES):
        if title not in existing:
            cat = Category(title=title, sort_order=order)
            session.add(cat)
            existing[title] = cat
    await session.flush()
    materials = existing[MATERIALS_TITLE]
    have = set((await session.scalars(
        select(SubCategory.title).where(SubCategory.category_id == materials.id))).all())
    for order, title in enumerate(MATERIAL_SUBCATEGORIES):
        if title not in have:
            session.add(SubCategory(category_id=materials.id, title=title, sort_order=order))
