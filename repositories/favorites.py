"""Репозиторий избранного."""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Company, Favorite
from repositories.companies import visible_clause


async def exists(s: AsyncSession, user_id: int, company_id: int) -> bool:
    q = select(Favorite.id).where(Favorite.user_id == user_id, Favorite.company_id == company_id)
    return await s.scalar(q) is not None


async def add(s: AsyncSession, user_id: int, company_id: int) -> None:
    s.add(Favorite(user_id=user_id, company_id=company_id))
    await s.flush()


async def remove(s: AsyncSession, user_id: int, company_id: int) -> None:
    await s.execute(delete(Favorite).where(Favorite.user_id == user_id, Favorite.company_id == company_id))


async def page(s: AsyncSession, user_id: int, offset: int, limit: int) -> tuple[list[Company], int]:
    """Видимые компании из избранного."""
    cond = [Favorite.user_id == user_id, visible_clause()]
    total = await s.scalar(select(func.count(Company.id)).select_from(Company)
                           .join(Favorite, Favorite.company_id == Company.id).where(*cond)) or 0
    q = (select(Company).options(selectinload(Company.category), selectinload(Company.subcategory))
         .join(Favorite, Favorite.company_id == Company.id).where(*cond)
         .order_by(Favorite.id.desc()).offset(offset).limit(limit))
    return list((await s.scalars(q)).all()), total


async def count_all(s: AsyncSession) -> int:
    return await s.scalar(select(func.count(Favorite.id))) or 0
