"""Репозиторий компаний: выборки каталога, поиск, модерация."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Category, Company, CompanyStatus, SubCategory, utcnow

# Вес тарифа для сортировки выдачи: VIP > Премиум > Стандарт
_TARIFF_WEIGHT = case({"vip": 3, "premium": 2, "standard": 1}, value=Company.tariff, else_=0)
_EAGER = (selectinload(Company.category), selectinload(Company.subcategory))


def visible_clause(now: datetime | None = None):
    """Условие «компания видна в каталоге»: одобрена и подписка действует."""
    return and_(Company.status == CompanyStatus.APPROVED, Company.subscription_until > (now or utcnow()))


def _like_escape(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get(s: AsyncSession, company_id: int) -> Company | None:
    return await s.scalar(select(Company).options(*_EAGER).where(Company.id == company_id))


async def get_by_owner(s: AsyncSession, owner_id: int) -> Company | None:
    return await s.scalar(select(Company).options(*_EAGER).where(Company.owner_id == owner_id))


async def catalog_page(
    s: AsyncSession, *, category_id: int | None = None, subcategory_id: int | None = None,
    tariff: str | None = None, tokens: list[tuple[str, list[int]]] | None = None, city: str | None = None,
    offset: int = 0, limit: int = 5,
) -> tuple[list[Company], int]:
    """Страница видимых компаний + общее количество. Сортировка: тариф, затем название."""
    cond = [visible_clause()]
    if category_id:
        cond.append(Company.category_id == category_id)
    if subcategory_id:
        cond.append(Company.subcategory_id == subcategory_id)
    if tariff:
        cond.append(Company.tariff == tariff)
    # tokens: [(основа слова, [id категорий, к которым относится вид работ])]; слово подходит, если оно есть
    # в тексте компании ИЛИ компания состоит в связанной категории (штукатурка -> Отделочные работы)
    for stem_, cat_ids in tokens or []:
        like = Company.search_text.like(f"%{_like_escape(stem_)}%", escape="\\")
        cond.append(or_(like, Company.category_id.in_(cat_ids)) if cat_ids else like)
    if city:
        cond.append(Company.city_key.like(f"%{_like_escape(city)}%", escape="\\"))
    total = await s.scalar(select(func.count(Company.id)).where(*cond)) or 0
    q = (select(Company).options(*_EAGER).where(*cond)
         .order_by(_TARIFF_WEIGHT.desc(), func.lower(Company.name), Company.id).offset(offset).limit(limit))
    return list((await s.scalars(q)).all()), total


async def admin_page(s: AsyncSession, *, status: str | None, offset: int, limit: int) -> tuple[list[Company], int]:
    cond = [Company.status == status] if status else []
    total = await s.scalar(select(func.count(Company.id)).where(*cond)) or 0
    q = select(Company).options(*_EAGER).where(*cond).order_by(Company.id.desc()).offset(offset).limit(limit)
    return list((await s.scalars(q)).all()), total


async def active_subscriptions_page(s: AsyncSession, offset: int, limit: int) -> tuple[list[Company], int]:
    cond = [Company.subscription_until > utcnow()]
    total = await s.scalar(select(func.count(Company.id)).where(*cond)) or 0
    q = (select(Company).options(*_EAGER).where(*cond).order_by(Company.subscription_until).offset(offset).limit(limit))
    return list((await s.scalars(q)).all()), total


async def with_subscription(s: AsyncSession) -> list[Company]:
    """Компании с действующей или недавно (≤ 2 дней) закончившейся подпиской — для планировщика."""
    border = utcnow() - timedelta(days=2)
    q = select(Company).where(Company.subscription_until > border, Company.status != CompanyStatus.PENDING)
    return list((await s.scalars(q)).all())


async def owner_tg_ids(s: AsyncSession) -> list[int]:
    from models import User  # локальный импорт, чтобы не раздувать шапку
    q = select(User.tg_id).join(Company, Company.owner_id == User.id).where(User.is_blocked.is_(False))
    return list((await s.scalars(q)).all())


async def all_companies(s: AsyncSession) -> list[Company]:
    return list((await s.scalars(select(Company).options(*_EAGER).order_by(Company.id))).all())


async def count_by_status(s: AsyncSession) -> dict[str, int]:
    rows = (await s.execute(select(Company.status, func.count(Company.id)).group_by(Company.status))).all()
    return {status: n for status, n in rows}


async def count_active(s: AsyncSession) -> int:
    return await s.scalar(select(func.count(Company.id)).where(visible_clause())) or 0


async def increment_views(s: AsyncSession, company_id: int) -> None:
    await s.execute(update(Company).where(Company.id == company_id).values(views=Company.views + 1))


async def delete_company(s: AsyncSession, company_id: int) -> None:
    """Удаляет компанию; связанные записи удаляются каскадом на уровне БД."""
    await s.execute(delete(Company).where(Company.id == company_id))


async def category_title_map(s: AsyncSession) -> dict[int, str]:
    rows = (await s.execute(select(Category.id, Category.title))).all()
    return {i: t for i, t in rows}


async def subcategory_title(s: AsyncSession, sub_id: int | None) -> str:
    if not sub_id:
        return ""
    return await s.scalar(select(SubCategory.title).where(SubCategory.id == sub_id)) or ""
