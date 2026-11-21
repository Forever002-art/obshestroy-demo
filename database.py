"""Подключение к БД: движок, фабрика сессий, базовый класс моделей."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей."""


if settings.sqlite_path:
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

# Для SQLite ждём освобождения блокировки до 30 с (вместо 5 с по умолчанию) — меньше ошибок «database is locked»
_connect_args = {"timeout": 30} if settings.is_sqlite else {}
engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args,
                             hide_parameters=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

if settings.is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
        """Включаем внешние ключи (каскадное удаление) и WAL для SQLite."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия с автокоммитом — для фоновых задач вне хендлеров."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
