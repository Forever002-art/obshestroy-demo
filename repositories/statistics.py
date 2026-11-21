"""Репозиторий статистики событий."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Statistic


async def add_events(s: AsyncSession, company_ids: list[int], event: str, user_id: int | None) -> None:
    s.add_all([Statistic(company_id=cid, event=event, user_id=user_id) for cid in company_ids])


async def counts_for_company(s: AsyncSession, company_id: int) -> dict[str, int]:
    q = select(Statistic.event, func.count(Statistic.id)).where(Statistic.company_id == company_id).group_by(
        Statistic.event)
    return {e: n for e, n in (await s.execute(q)).all()}


async def counts_total(s: AsyncSession) -> dict[str, int]:
    q = select(Statistic.event, func.count(Statistic.id)).group_by(Statistic.event)
    return {e: n for e, n in (await s.execute(q)).all()}
