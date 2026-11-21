"""Пользовательские фильтры."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import settings


class AdminFilter(BaseFilter):
    """Пропускает только администраторов из ADMIN_IDS."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return bool(event.from_user and event.from_user.id in settings.admin_ids)
