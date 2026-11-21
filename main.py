"""Точка входа: python main.py"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import BaseStorage
from aiogram.types import ErrorEvent

from config import BASE_DIR, settings
from database import engine, session_scope
from handlers import admin, company, user
from middlewares import DbSessionMiddleware, ThrottlingMiddleware
from scheduler import setup_scheduler
from utils.logging_setup import setup_logging
from utils.seed import seed_categories

log = logging.getLogger(__name__)


def run_migrations() -> None:
    """Применяет миграции Alembic (запускается в отдельном потоке — у Alembic свой event loop)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    command.upgrade(cfg, "head")


async def on_error(event: ErrorEvent) -> bool:
    """Глобальный обработчик ошибок: логируем и вежливо отвечаем пользователю."""
    log.exception("Необработанная ошибка: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Произошла ошибка. Попробуйте ещё раз.", show_alert=True)
        elif update.message:
            await update.message.answer("⚠️ Произошла ошибка. Попробуйте ещё раз позже.")
    except Exception:  # noqa: BLE001
        pass
    return True


def make_bot() -> Bot:
    http_session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else None
    return Bot(settings.bot_token, session=http_session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def make_dispatcher(storage: BaseStorage, *, polling: bool = False) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    dp.update.outer_middleware(DbSessionMiddleware())
    # Порядок важен: кнопки главного меню (user) сбрасывают FSM раньше остальных обработчиков
    dp.include_routers(user.router, admin.router, company.router)
    if polling:
        dp.callback_query.middleware(ThrottlingMiddleware())
        dp.errors.register(on_error)
    return dp


async def prepare_database(*, migrate: bool) -> None:
    if migrate:
        await asyncio.to_thread(run_migrations)
    async with session_scope() as session:
        await seed_categories(session)


async def main() -> None:
    setup_logging()
    await prepare_database(migrate=settings.auto_migrate)
    bot = make_bot()
    dp = make_dispatcher(MemoryStorage(), polling=True)
    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("Бот запущен. Администраторы: %s", sorted(settings.admin_ids))
    try:
        if (await bot.get_webhook_info()).url:
            raise RuntimeError("У бота настроен вебхук. Для локальной разработки используйте отдельного бота.")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), polling_timeout=30)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


async def init_db() -> None:
    try:
        await prepare_database(migrate=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        asyncio.run(init_db() if sys.argv[1:] == ["--init-db"] else main(), loop_factory=loop_factory)
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен")
