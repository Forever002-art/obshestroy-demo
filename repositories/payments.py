"""Репозиторий платежей и подписок."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Payment, PaymentStatus, Subscription


async def add_payment(s: AsyncSession, **kwargs) -> Payment:
    payment = Payment(**kwargs)
    s.add(payment)
    await s.flush()
    return payment


async def get_payment(s: AsyncSession, payment_id: int) -> Payment | None:
    return await s.get(Payment, payment_id)


async def income_since(s: AsyncSession, since: datetime | None) -> tuple[int, int]:
    """(сумма в рублях, число платежей) начиная с даты; None — за всё время."""
    q = select(func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id)).where(
        Payment.status == PaymentStatus.PAID, Payment.amount > 0)
    if since:
        q = q.where(Payment.paid_at >= since)
    row = (await s.execute(q)).one()
    return int(row[0]), int(row[1])


async def income_by_tariff(s: AsyncSession) -> list[tuple[str, int, int]]:
    q = (select(Payment.tariff, func.sum(Payment.amount), func.count(Payment.id))
         .where(Payment.status == PaymentStatus.PAID, Payment.amount > 0).group_by(Payment.tariff))
    return [(t, int(a or 0), int(n)) for t, a, n in (await s.execute(q)).all()]


async def has_trial(s: AsyncSession, company_id: int) -> bool:
    q = select(Payment.id).where(Payment.company_id == company_id, Payment.provider == "trial")
    return await s.scalar(q) is not None


async def add_subscription(s: AsyncSession, **kwargs) -> Subscription:
    sub = Subscription(**kwargs)
    s.add(sub)
    await s.flush()
    return sub


async def deactivate_company_subscriptions(s: AsyncSession, company_id: int) -> None:
    await s.execute(update(Subscription).where(Subscription.company_id == company_id,
                                               Subscription.is_active.is_(True)).values(is_active=False))


async def count_active_subscriptions(s: AsyncSession) -> int:
    return await s.scalar(select(func.count(Subscription.id)).where(Subscription.is_active.is_(True))) or 0
