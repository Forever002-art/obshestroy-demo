"""Бизнес-логика компаний: поля, валидация, создание, модерация."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from config import TARIFFS
from models import Company, CompanyStatus, User
from repositories import categories as cat_repo
from repositories import companies as repo
from utils import validators as v
from utils.formatting import normalize, truncate
from utils.logging_setup import company_log, registration_log


@dataclass(frozen=True, slots=True)
class Field:
    """Описание редактируемого поля компании."""

    key: str
    title: str
    validator: Callable[[str], str]
    required: bool = True
    hint: str = ""


FIELDS: dict[str, Field] = {f.key: f for f in (
    Field("name", "Название", v.text_field(2, 100)),
    Field("description", "Описание", v.text_field(10, 2000), hint="Расскажите о компании: чем занимаетесь, опыт, преимущества."),
    Field("services", "Услуги", v.text_field(2, 1500), False, "Перечислите услуги (каждая с новой строки или через запятую)."),
    Field("materials", "Материалы", v.text_field(2, 1500), False, "Перечислите строительные материалы, которые вы продаёте/производите."),
    Field("country", "Страна", v.text_field(2, 80)),
    Field("region", "Регион", v.text_field(2, 120), hint="Область, край или республика."),
    Field("city", "Город", v.text_field(2, 120)),
    Field("address", "Адрес", v.text_field(3, 255), hint="Улица, дом, офис."),
    Field("work_hours", "График работы", v.text_field(3, 200), hint="Например: Пн–Пт 9:00–18:00, Сб 10:00–15:00."),
    Field("phone", "Телефон", v.phone, False, "Например: +7 900 123-45-67"),
    Field("telegram", "Telegram username", v.telegram, False, "Например: @company_name"),
    Field("email", "Email", v.email, False, "Например: info@company.ru"),
    Field("website", "Сайт", v.website, False, "Например: https://company.ru"),
)}
CONTACT_FIELDS = ("phone", "telegram", "email", "website")
# Поля, у которых «пусто» хранится как пустая строка, а не NULL
_EMPTY_STRING_FIELDS = {"services", "materials"}


def photo_limit(company: Company) -> int:
    tariff = TARIFFS.get(company.tariff or "standard", TARIFFS["standard"])
    return tariff.max_photos


async def refresh_search_text(s: AsyncSession, company: Company) -> None:
    """Пересобирает нормализованный текст для поиска."""
    cat = await cat_repo.get_category(s, company.category_id)
    sub = await cat_repo.get_subcategory(s, company.subcategory_id) if company.subcategory_id else None
    chunks = [company.name, company.short_description, company.description, company.services, company.materials,
              cat.title if cat else "", sub.title if sub else "", company.country, company.region,
              company.city, company.address]
    company.search_text = normalize(" ".join(c for c in chunks if c))
    company.city_key = normalize(company.city or "")


async def update_field(s: AsyncSession, company: Company, key: str, raw: str) -> str | None:
    """Меняет поле. Возвращает текст ошибки или None при успехе."""
    field = FIELDS[key]
    if not field.required and v.is_skip(raw):
        setattr(company, key, "" if key in _EMPTY_STRING_FIELDS else None)
    else:
        try:
            value = field.validator(raw)
        except ValueError as exc:
            return str(exc)
        setattr(company, key, value)
        if key == "description":
            company.short_description = truncate(value.split("\n")[0], 150)
    await refresh_search_text(s, company)
    company_log.info("company=%s field=%s changed", company.id, key)
    return None


async def set_category(s: AsyncSession, company: Company, category_id: int, sub_id: int | None) -> None:
    company.category_id, company.subcategory_id = category_id, sub_id
    await refresh_search_text(s, company)
    company_log.info("company=%s category -> %s/%s", company.id, category_id, sub_id)


async def create_company(s: AsyncSession, owner: User, data: dict) -> Company:
    """Создаёт заявку компании (или обновляет ранее отклонённую). Статус — «на модерации»."""
    company = await repo.get_by_owner(s, owner.id)
    if company is None:
        company = Company(owner_id=owner.id, category_id=data["category_id"])
        s.add(company)
    values = {k: data.get(k) for k in FIELDS}
    for key, val in values.items():
        setattr(company, key, val if val is not None or key not in _EMPTY_STRING_FIELDS else "")
    company.category_id = data["category_id"]
    company.subcategory_id = data.get("subcategory_id")
    company.short_description = truncate((data["description"].split("\n")[0]), 150)
    company.logo_file_id = data.get("logo")
    company.photos = list(data.get("photos", []))
    company.status, company.reject_reason = CompanyStatus.PENDING, None
    await s.flush()
    await refresh_search_text(s, company)
    registration_log.info("company=%s registered by user=%s", company.id, owner.tg_id)
    return company


async def set_status(s: AsyncSession, company: Company, status: str, reason: str | None = None) -> None:
    company.status = status
    company.reject_reason = reason if status == CompanyStatus.REJECTED else None
    company_log.info("company=%s status -> %s", company.id, status)
