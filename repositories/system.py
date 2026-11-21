"""Репозиторий служебных таблиц: уведомления, журнал админа, настройки."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AdminLog, Notification, Setting
from utils.seed import DEFAULT_SETTINGS


async def reserve_notification(s: AsyncSession, tg_id: int, kind: str, text: str, dedupe_key: str | None) -> Notification | None:
    """Создаёт запись уведомления. Если dedupe_key уже использовался — возвращает None (дубль)."""
    if dedupe_key and await s.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)):
        return None
    note = Notification(user_tg_id=tg_id, kind=kind, text=text, dedupe_key=dedupe_key)
    s.add(note)
    await s.flush()
    return note


async def add_admin_log(s: AsyncSession, admin_tg_id: int, action: str, target: str = "", details: str = "") -> None:
    s.add(AdminLog(admin_tg_id=admin_tg_id, action=action, target=target, details=details))


async def get_setting(s: AsyncSession, key: str) -> str:
    row = await s.get(Setting, key)
    return row.value if row else DEFAULT_SETTINGS.get(key, "")


async def set_setting(s: AsyncSession, key: str, value: str) -> None:
    row = await s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))
