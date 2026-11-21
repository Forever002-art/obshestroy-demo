"""Middleware: сессия БД, регистрация пользователя, антифлуд."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from config import settings
from database import session_scope
from repositories import users as user_repo

log = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию на каждое обновление, регистрирует пользователя, блокирует забаненных.

    В data добавляются: session, db_user, is_admin. Коммит — после успешной обработки.
    """

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: Update, data: dict[str, Any]) -> Any:
        webhook_session = data.get("webhook_session")
        if webhook_session is not None:
            return await self._handle(handler, event, data, webhook_session, polling=False)
        async with session_scope() as session:
            return await self._handle(handler, event, data, session, polling=True)

    async def _handle(self, handler, event, data, session, *, polling):
        tg_user = data.get("event_from_user")
        data["session"] = session
        if tg_user and not tg_user.is_bot:
            user = await user_repo.get_or_create(session, tg_user.id, tg_user.username, tg_user.full_name)
            if polling:
                await session.commit()  # Не держим блокировку SQLite на время ответа Telegram.
            data["db_user"] = user
            data["is_admin"] = tg_user.id in settings.admin_ids
            if user.is_blocked and not data["is_admin"]:
                if event.callback_query:
                    await event.callback_query.answer("⛔ Вы заблокированы.", show_alert=True)
                elif event.message:
                    await event.message.answer("⛔ Ваш доступ к боту ограничен.")
                return None
        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    """Защита от двойных нажатий inline-кнопок (подключается только к callback_query, сообщения не теряются)."""

    def __init__(self, interval: float = 0.3) -> None:
        self.interval = interval
        self._last: dict[int, float] = {}

    async def __call__(self, handler, event, data):  # noqa: ANN001
        user = data.get("event_from_user")
        # Фото (альбомы) пропускаем — пользователь может отправить несколько сразу
        if user and not getattr(event, "photo", None):
            now = time.monotonic()
            if now - self._last.get(user.id, 0) < self.interval:
                if hasattr(event, "answer") and event.__class__.__name__ == "CallbackQuery":
                    await event.answer()
                return None
            self._last[user.id] = now
            if len(self._last) > 10_000:
                self._last.clear()
        return await handler(event, data)
