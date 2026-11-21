"""Валидация и нормализация пользовательского ввода."""
from __future__ import annotations

import re

SKIP_VALUES = {"-", "—", "–", "нет", "пропустить"}
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{5,19}$")
_TG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_SITE_RE = re.compile(r"^(https?://)?([\w\-]+\.)+[A-Za-z]{2,}(/\S*)?$")


def is_skip(text: str) -> bool:
    return text.strip().lower() in SKIP_VALUES


def text_field(min_len: int, max_len: int):
    """Фабрика валидатора обычного текста."""
    def _v(raw: str) -> str:
        value = raw.strip()
        if len(value) < min_len:
            raise ValueError(f"Слишком коротко — минимум {min_len} симв.")
        if len(value) > max_len:
            raise ValueError(f"Слишком длинно — максимум {max_len} симв. (сейчас {len(value)}).")
        return value
    return _v


def phone(raw: str) -> str:
    value = raw.strip()
    if not _PHONE_RE.match(value):
        raise ValueError("Некорректный телефон. Пример: +7 900 123-45-67")
    return value


def telegram(raw: str) -> str:
    value = raw.strip().removeprefix("https://t.me/").removeprefix("t.me/").lstrip("@")
    if not _TG_RE.match(value):
        raise ValueError("Некорректный username. Пример: @company_name (5–32 символа, латиница/цифры/_)")
    return "@" + value


def email(raw: str) -> str:
    value = raw.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError("Некорректный e-mail. Пример: info@company.ru")
    return value


def website(raw: str) -> str:
    value = raw.strip()
    if not _SITE_RE.match(value):
        raise ValueError("Некорректный адрес сайта. Пример: https://company.ru")
    return value if value.startswith("http") else "https://" + value
