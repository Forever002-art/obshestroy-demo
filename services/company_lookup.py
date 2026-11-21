"""Поиск организаций в официальном реестре (ЕГРЮЛ/ЕГРИП) через DaData для автозаполнения заявки.

Нужен токен DADATA_TOKEN (dadata.ru → личный кабинет → API-ключ). Без токена функция отключена.
Реестр содержит название, адрес, регион, ОКВЭД; телефон/e-mail бывают не всегда.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config import settings
from utils import validators as v
from utils.catalog_data import CATEGORIES

log = logging.getLogger(__name__)
_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"

# Префикс ОКВЭД -> индекс категории в CATEGORIES (берётся самый длинный подходящий префикс)
_OKVED_TO_CATEGORY: dict[str, int] = {
    "41": 0, "42": 1, "43.11": 8, "43.12": 2, "43.21": 9, "43.22.2": 11, "43.22": 10, "43.29": 9,
    "43.31": 7, "43.32": 5, "43.33": 7, "43.34": 7, "43.39": 7, "43.91": 4, "43.99": 1,
    "16.2": 5, "16.1": 5, "31": 6, "23.6": 20, "24": 20, "25": 20, "46.73": 22, "47.52": 22,
    "49.41": 18, "77.32": 19, "71.1": 21, "81.3": 17,
}


@dataclass(slots=True)
class Hint:
    """Вариант организации из реестра."""

    name: str
    inn: str
    country: str
    region: str
    city: str
    address: str
    phone: str
    email: str
    category_title: str


def _get(data, *path, default=""):
    for key in path:
        if not isinstance(data, dict):
            return default
        data = data.get(key)
        if data is None:
            return default
    return data


def category_for_okved(code: str) -> str:
    """Название категории каталога по коду ОКВЭД ('' — если не удалось определить)."""
    for prefix in sorted(_OKVED_TO_CATEGORY, key=len, reverse=True):
        if code.startswith(prefix):
            return CATEGORIES[_OKVED_TO_CATEGORY[prefix]]
    return ""


def _contact(items, validator) -> str:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        try:
            return validator(str(items[0].get("value", "")))
        except ValueError:
            return ""
    return ""


def parse_suggestion(item: dict) -> Hint | None:
    """Преобразует один элемент ответа DaData в Hint."""
    data = item.get("data") or {}
    name = _get(data, "name", "short_with_opf") or item.get("value") or ""
    if not name:
        return None
    addr = _get(data, "address", "data", default={}) or {}
    parts = [addr.get("street_with_type"),
             " ".join(x for x in (addr.get("house_type"), addr.get("house")) if x),
             " ".join(x for x in (addr.get("block_type"), addr.get("block")) if x),
             " ".join(x for x in (addr.get("flat_type"), addr.get("flat")) if x)]
    address = ", ".join(p for p in parts if p) or _get(data, "address", "value")
    return Hint(
        name=name[:100], inn=str(data.get("inn") or ""), country=addr.get("country") or "Россия",
        region=(addr.get("region_with_type") or "")[:120],
        city=(addr.get("city") or addr.get("settlement") or "")[:120], address=address[:255],
        phone=_contact(data.get("phones"), v.phone), email=_contact(data.get("emails"), v.email),
        category_title=category_for_okved(str(data.get("okved") or "")),
    )


async def suggest(name: str, city: str | None, count: int = 7) -> list[Hint]:
    """Ищет организации по названию (и городу). При любой ошибке возвращает [] — регистрация идёт вручную."""
    if not settings.dadata_token:
        return []
    import aiohttp  # входит в зависимости aiogram

    headers = {"Authorization": f"Token {settings.dadata_token}", "Content-Type": "application/json",
               "Accept": "application/json"}
    base = {"query": name, "count": count, "status": ["ACTIVE"]}
    bodies = [{**base, "locations": [{"city": city}]}, base] if city else [base]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8), headers=headers) as http:
            for body in bodies:
                async with http.post(_URL, json=body) as resp:
                    if resp.status != 200:
                        log.warning("DaData вернула статус %s", resp.status)
                        continue
                    payload = await resp.json()
                hints = [h for h in (parse_suggestion(i) for i in payload.get("suggestions", [])) if h]
                if hints:
                    return hints[:count]
    except Exception:  # noqa: BLE001 — сеть/таймаут/формат: просто продолжаем вручную
        log.exception("Ошибка запроса к DaData")
    return []
