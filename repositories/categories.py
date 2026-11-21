"""Репозиторий категорий и подкатегорий."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Category, SubCategory


async def all_categories(s: AsyncSession) -> list[Category]:
    return list((await s.scalars(select(Category).order_by(Category.sort_order))).all())


async def get_category(s: AsyncSession, category_id: int) -> Category | None:
    return await s.get(Category, category_id)


async def subcategories(s: AsyncSession, category_id: int) -> list[SubCategory]:
    q = select(SubCategory).where(SubCategory.category_id == category_id).order_by(SubCategory.sort_order)
    return list((await s.scalars(q)).all())


async def get_subcategory(s: AsyncSession, sub_id: int) -> SubCategory | None:
    return await s.get(SubCategory, sub_id)
