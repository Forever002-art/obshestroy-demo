"""Сервис статистики."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models import Company
from repositories import companies as company_repo
from repositories import favorites as fav_repo
from repositories import payments as pay_repo
from repositories import reviews as review_repo
from repositories import statistics as repo
from repositories import users as user_repo


async def record(s: AsyncSession, company_id: int, event: str, user_id: int | None = None) -> None:
    await repo.add_events(s, [company_id], event, user_id)


async def record_many(s: AsyncSession, companies: list[Company], event: str, user_id: int | None = None) -> None:
    if companies:
        await repo.add_events(s, [c.id for c in companies], event, user_id)


async def company_counts(s: AsyncSession, company_id: int) -> tuple[dict[str, int], int]:
    """(события, число отзывов)."""
    _, reviews = await review_repo.rating(s, company_id)
    return await repo.counts_for_company(s, company_id), reviews


async def global_stats(s: AsyncSession) -> dict:
    return {
        "users": await user_repo.count(s),
        "companies": await company_repo.count_by_status(s),
        "visible": await company_repo.count_active(s),
        "subscriptions": await pay_repo.count_active_subscriptions(s),
        "reviews": await review_repo.count(s),
        "favorites": await fav_repo.count_all(s),
        "events": await repo.counts_total(s),
    }
