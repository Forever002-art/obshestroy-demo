"""Платежи и подписки."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from config import SUBSCRIPTION_DAYS_PER_MONTH, TARIFFS, TRIAL_TARIFF, settings
from models import Company, Payment, PaymentStatus, User, utcnow
from repositories import payments as repo
from utils.logging_setup import payment_log


async def create_payment(s: AsyncSession, company: Company, user: User, tariff_code: str, months: int,
                         provider: str) -> Payment:
    tariff = TARIFFS[tariff_code]
    payment = await repo.add_payment(
        s, company_id=company.id, user_id=user.id, tariff=tariff_code, months=months,
        amount=tariff.price * months, currency=settings.currency, provider=provider)
    payment_log.info("payment=%s created company=%s tariff=%s months=%s amount=%s provider=%s",
                     payment.id, company.id, tariff_code, months, payment.amount, provider)
    return payment


async def activate_subscription(s: AsyncSession, company: Company, tariff_code: str, days: int,
                                payment_id: int | None = None) -> None:
    """Продлевает подписку: при том же тарифе срок добавляется к текущему, при смене тарифа — отсчёт с «сейчас»."""
    now = utcnow()
    same_active = (company.tariff == tariff_code and company.subscription_until
                   and company.subscription_until > now)
    start = company.subscription_until if same_active else now
    ends = start + timedelta(days=days)
    await repo.deactivate_company_subscriptions(s, company.id)
    await repo.add_subscription(s, company_id=company.id, tariff=tariff_code, starts_at=now, ends_at=ends,
                                is_active=True, payment_id=payment_id)
    company.tariff, company.subscription_until = tariff_code, ends
    payment_log.info("company=%s subscription %s until %s", company.id, tariff_code, ends)


async def confirm_payment(s: AsyncSession, payment: Payment, company: Company, charge_id: str | None = None) -> bool:
    """Помечает платёж оплаченным и активирует подписку. False — если уже обработан."""
    if payment.status == PaymentStatus.PAID:
        return False
    payment.status, payment.paid_at, payment.provider_charge_id = PaymentStatus.PAID, utcnow(), charge_id
    await activate_subscription(s, company, payment.tariff, payment.months * SUBSCRIPTION_DAYS_PER_MONTH, payment.id)
    payment_log.info("payment=%s PAID charge=%s", payment.id, charge_id)
    return True


async def admin_extend(s: AsyncSession, company: Company, tariff_code: str, days: int, admin_tg_id: int) -> None:
    """Бесплатное продление администратором (в доход не входит)."""
    payment = await repo.add_payment(s, company_id=company.id, user_id=company.owner_id, tariff=tariff_code,
                                     months=max(days // SUBSCRIPTION_DAYS_PER_MONTH, 1), amount=0,
                                     currency=settings.currency, status=PaymentStatus.PAID, provider="admin",
                                     paid_at=utcnow())
    await activate_subscription(s, company, tariff_code, days, payment.id)
    payment_log.info("admin=%s extended company=%s %s +%sd", admin_tg_id, company.id, tariff_code, days)


async def finalize(s: AsyncSession, bot, payment: Payment, charge_id: str | None = None) -> bool:
    """Подтверждает платёж, активирует подписку и уведомляет владельца. False — если платёж уже обработан."""
    from repositories import companies as company_repo
    from repositories import users as user_repo
    from services.notification_service import NotificationService, t_purchased

    company = await company_repo.get(s, payment.company_id) if payment.company_id else None
    if company is None or not await confirm_payment(s, payment, company, charge_id):
        return False
    owner = await user_repo.get(s, company.owner_id)
    if owner:
        await NotificationService(bot).send(s, owner.tg_id, t_purchased(company.name, payment.tariff, company.subscription_until),
                                            "purchase")
    return True


async def grant_trial(s: AsyncSession, company: Company) -> bool:
    """Пробная подписка при первом одобрении компании (один раз). False — если отключена или уже выдавалась."""
    if settings.trial_days <= 0 or await repo.has_trial(s, company.id):
        return False
    payment = await repo.add_payment(
        s, company_id=company.id, user_id=company.owner_id, tariff=TRIAL_TARIFF,
        months=max(settings.trial_days // SUBSCRIPTION_DAYS_PER_MONTH, 1), amount=0, currency=settings.currency,
        status=PaymentStatus.PAID, provider="trial", paid_at=utcnow())
    await activate_subscription(s, company, TRIAL_TARIFF, settings.trial_days, payment.id)
    payment_log.info("company=%s trial %s days granted", company.id, settings.trial_days)
    return True
