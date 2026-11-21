"""Отправка уведомлений и рассылок + шаблоны сообщений."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from config import TARIFFS, TRIAL_TARIFF, settings
from repositories import system as repo
from utils.formatting import esc, fmt_dt

log = logging.getLogger(__name__)


class NotificationService:
    """Обёртка над Bot для безопасной отправки и журналирования уведомлений."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, s: AsyncSession, tg_id: int, text: str, kind: str, dedupe_key: str | None = None,
                   kb: InlineKeyboardMarkup | None = None) -> bool:
        note = await repo.reserve_notification(s, tg_id, kind, text, dedupe_key)
        if note is None:
            return False  # такое уведомление уже отправлялось
        try:
            await self.bot.send_message(tg_id, text, reply_markup=kb)
            note.is_sent = True
        except TelegramAPIError as exc:
            log.warning("Не удалось отправить уведомление %s -> %s: %s", kind, tg_id, exc)
        return note.is_sent

    async def notify_admins(self, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
        for admin_id in settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text, reply_markup=kb)
            except TelegramAPIError as exc:
                log.warning("Админ %s недоступен: %s", admin_id, exc)

    async def broadcast(self, tg_ids: list[int], text: str) -> tuple[int, int]:
        """Рассылка с ограничением скорости (~20 сообщений/сек). Возвращает (доставлено, ошибок)."""
        ok = fail = 0
        for tg_id in tg_ids:
            try:
                await self.bot.send_message(tg_id, text)
                ok += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                try:
                    await self.bot.send_message(tg_id, text)
                    ok += 1
                except TelegramAPIError:
                    fail += 1
            except TelegramAPIError:
                fail += 1
            await asyncio.sleep(0.05)
        return ok, fail


# ---------- Шаблоны сообщений ----------
def _prices() -> str:
    return " · ".join(f"{t.title} — {t.price} ₽/мес" for t in TARIFFS.values())


def t_registered(name: str) -> str:
    trial = f"\n🎁 После одобрения вы получите бесплатный пробный период — {settings.trial_days} дн." if settings.trial_days > 0 else ""
    return (f"📨 Заявка на размещение «{esc(name)}» отправлена на модерацию.\n"
            f"Мы сообщим о решении в этом чате.{trial}")


def t_approved(name: str, trial_until=None) -> str:
    if settings.demo_mode:
        until = f"Карточка доступна в каталоге до {fmt_dt(trial_until, True)}." if trial_until else ""
        return f"✅ Компания «{esc(name)}» одобрена.\n\n{until}".strip()
    if trial_until:
        return (f"✅ Компания «{esc(name)}» одобрена!\n\n"
                f"🎁 Вам подарен пробный период (тариф «{TARIFFS[TRIAL_TARIFF].title}») до {fmt_dt(trial_until, True)} — "
                f"карточка уже в каталоге.\n\nПосле пробного периода: {_prices()}.\n"
                "Оформить подписку: Главная → Личный кабинет → Подписка.")
    return (f"✅ Компания «{esc(name)}» одобрена!\n\nЧтобы карточка появилась в каталоге, оформите подписку: "
            f"Главная → Личный кабинет → Подписка.\nТарифы: {_prices()}.")


def t_rejected(name: str, reason: str | None) -> str:
    return f"❌ Заявка «{esc(name)}» отклонена.\nПричина: {esc(reason or 'не указана')}\n\nВы можете исправить данные и подать заявку заново."


def t_purchased(name: str, tariff: str, until) -> str:
    t = TARIFFS[tariff]
    return (f"💳 Подписка оформлена!\n\nКомпания: «{esc(name)}»\nТариф: {t.mark} {t.title}\n"
            f"Действует до: {fmt_dt(until, True)}")


def t_expiring(name: str, kind: str, until) -> str:
    when = {"7d": "через 7 дней", "3d": "через 3 дня", "today": "сегодня"}[kind]
    renewal = "Для продления обратитесь к администратору." if settings.demo_mode else (
        "Продлите её, чтобы карточка оставалась в каталоге."
    )
    return (f"⏰ Подписка компании «{esc(name)}» заканчивается {when} ({fmt_dt(until, True)}).\n"
            f"{renewal}")


def t_expired(name: str) -> str:
    renewal = "Для продления обратитесь к администратору." if settings.demo_mode else "Оформите подписку заново."
    return f"⌛ Подписка компании «{esc(name)}» закончилась. Карточка скрыта из каталога. {renewal}"


def t_new_review(name: str, rating: int, text: str) -> str:
    return f"⭐ Новый отзыв о «{esc(name)}»\nОценка: {rating}/5\n\n{esc(text)}"
