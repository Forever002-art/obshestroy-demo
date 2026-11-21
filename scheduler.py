"""Планировщик APScheduler: проверка подписок, уведомления, автобэкап."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import session_scope
from models import utcnow
from repositories import companies as company_repo
from repositories import payments as pay_repo
from repositories import users as user_repo
from services import backup_service
from services.notification_service import NotificationService, t_expired, t_expiring

log = logging.getLogger(__name__)


async def check_subscriptions(bot: Bot) -> None:
    """Отключает просроченные подписки и рассылает напоминания (7 дней / 3 дня / в день окончания / после).

    Каждое уведомление защищено dedupe_key — повторно не отправляется, даже при перезапусках.
    """
    now = utcnow()
    today_local = datetime.now(settings.tz).date()
    notifier = NotificationService(bot)
    async with session_scope() as s:
        for company in await company_repo.with_subscription(s):
            owner = await user_repo.get(s, company.owner_id)
            until = company.subscription_until
            if owner is None or until is None:
                continue
            stamp = f"{until:%Y%m%d%H%M}"
            if until <= now:
                await pay_repo.deactivate_company_subscriptions(s, company.id)
                await notifier.send(s, owner.tg_id, t_expired(company.name), "expired", f"expired:{company.id}:{stamp}")
                continue
            until_local = until.replace(tzinfo=timezone.utc).astimezone(settings.tz).date()
            left = until - now
            if until_local == today_local:
                kind = "today"
            elif left <= timedelta(days=3):
                kind = "3d"
            elif left <= timedelta(days=7):
                kind = "7d"
            else:
                continue
            await notifier.send(s, owner.tg_id, t_expiring(company.name, kind, until), f"expiring_{kind}",
                                f"expiring_{kind}:{company.id}:{stamp}")


async def _safe(coro_func, *args) -> None:
    """Фоновая задача не должна ронять планировщик."""
    try:
        await coro_func(*args)
    except Exception:  # noqa: BLE001
        log.exception("Ошибка фоновой задачи %s", getattr(coro_func, "__name__", coro_func))


async def auto_backup() -> None:
    await backup_service.create_backup()


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(_safe, "interval", minutes=30, args=[check_subscriptions, bot], id="subscriptions",
                      next_run_time=datetime.now(settings.tz) + timedelta(seconds=10), max_instances=1, coalesce=True)
    if settings.is_sqlite:
        scheduler.add_job(_safe, "cron", hour=3, minute=0, args=[auto_backup], id="backup", coalesce=True)
    return scheduler
