"""Мелкие функции форматирования текста, дат и денег."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from config import settings


def esc(value: object) -> str:
    """Экранирование пользовательского текста для parse_mode=HTML."""
    return escape(str(value), quote=False)


def dash(value: str | None) -> str:
    """Пустые значения показываем прочерком."""
    return esc(value) if value and str(value).strip() else "—"


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def fmt_dt(value: datetime | None, with_time: bool = False) -> str:
    """UTC (naive) -> локальное время в настроенной таймзоне."""
    if not value:
        return "—"
    local = value.replace(tzinfo=timezone.utc).astimezone(settings.tz)
    return local.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def stars(avg: float) -> str:
    full = int(round(avg))
    return "★" * full + "☆" * (5 - full)


def pages_count(total: int, size: int) -> int:
    return max((total + size - 1) // size, 1)


def normalize(text: str) -> str:
    """Нормализация для поиска: casefold + «ё»→«е» + схлопывание пробелов."""
    return " ".join(text.casefold().replace("ё", "е").split())


def stem(token: str) -> str:
    """Грубое отсечение русских окончаний: «лестница» найдёт «лестницы», «Москве» — «Москва»."""
    if len(token) > 5:
        return token[:-2]
    if len(token) > 4:
        return token[:-1]
    return token
