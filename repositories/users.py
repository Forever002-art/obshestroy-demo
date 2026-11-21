"""Репозиторий пользователей."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, utcnow


async def get_by_tg(s: AsyncSession, tg_id: int) -> User | None:
    return await s.scalar(select(User).where(User.tg_id == tg_id))


async def get(s: AsyncSession, user_id: int) -> User | None:
    return await s.get(User, user_id)


async def get_or_create(s: AsyncSession, tg_id: int, username: str | None, full_name: str) -> User:
    """Возвращает пользователя; создаёт или обновляет профиль при необходимости."""
    user = await get_by_tg(s, tg_id)
    if user is None:
        user = User(tg_id=tg_id, username=username, full_name=full_name)
        s.add(user)
        await s.flush()
        return user
    now = utcnow()
    # Пишем в БД только при изменениях: каждая запись — это блокировка SQLite
    if user.username != username or user.full_name != full_name or now - user.last_active_at > timedelta(minutes=5):
        user.username, user.full_name, user.last_active_at = username, full_name, now
    return user


async def set_city(s: AsyncSession, user: User, city: str) -> None:
    user.city = city


async def count(s: AsyncSession) -> int:
    return await s.scalar(select(func.count(User.id))) or 0


async def page(s: AsyncSession, offset: int, limit: int) -> list[User]:
    q = select(User).order_by(User.id.desc()).offset(offset).limit(limit)
    return list((await s.scalars(q)).all())


async def all_users(s: AsyncSession) -> list[User]:
    return list((await s.scalars(select(User).order_by(User.id))).all())


async def broadcast_ids(s: AsyncSession) -> list[int]:
    """Telegram ID всех неблокированных пользователей."""
    return list((await s.scalars(select(User.tg_id).where(User.is_blocked.is_(False)))).all())


async def set_blocked(s: AsyncSession, user_id: int, blocked: bool) -> None:
    await s.execute(update(User).where(User.id == user_id).values(is_blocked=blocked))
