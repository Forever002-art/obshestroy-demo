"""Репозиторий отзывов."""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Company, Review, User


async def get(s: AsyncSession, review_id: int) -> Review | None:
    return await s.get(Review, review_id)


async def get_user_review(s: AsyncSession, company_id: int, user_id: int) -> Review | None:
    return await s.scalar(select(Review).where(Review.company_id == company_id, Review.user_id == user_id))


async def add(s: AsyncSession, company_id: int, user_id: int, rating: int, text: str) -> Review:
    review = Review(company_id=company_id, user_id=user_id, rating=rating, text=text)
    s.add(review)
    await s.flush()
    return review


async def rating(s: AsyncSession, company_id: int) -> tuple[float, int]:
    """(средняя оценка, количество отзывов)."""
    row = (await s.execute(select(func.avg(Review.rating), func.count(Review.id))
                           .where(Review.company_id == company_id))).one()
    return float(row[0] or 0), int(row[1] or 0)


async def latest(s: AsyncSession, company_id: int, limit: int = 5) -> list[tuple[Review, User]]:
    q = (select(Review, User).join(User, User.id == Review.user_id)
         .where(Review.company_id == company_id).order_by(Review.id.desc()).limit(limit))
    return [(r, u) for r, u in (await s.execute(q)).all()]


async def admin_page(s: AsyncSession, offset: int, limit: int) -> tuple[list[tuple[Review, str]], int]:
    total = await s.scalar(select(func.count(Review.id))) or 0
    q = (select(Review, Company.name).join(Company, Company.id == Review.company_id)
         .order_by(Review.id.desc()).offset(offset).limit(limit))
    return [(r, n) for r, n in (await s.execute(q)).all()], total


async def delete_review(s: AsyncSession, review_id: int) -> None:
    await s.execute(delete(Review).where(Review.id == review_id))


async def count(s: AsyncSession) -> int:
    return await s.scalar(select(func.count(Review.id))) or 0
