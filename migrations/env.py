"""Окружение Alembic (async). Работает и с SQLite (aiosqlite), и с PostgreSQL (asyncpg)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from database import Base  # noqa: E402
import models  # noqa: E402,F401  (регистрирует таблицы в metadata)
import models.webhook  # noqa: E402,F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # noqa: ANN001
    # render_as_batch — чтобы ALTER TABLE работал в SQLite
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(run_migrations_online(), loop_factory=loop_factory)
