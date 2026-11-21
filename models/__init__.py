"""ORM-модели проекта."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo (единый формат хранения во всех СУБД)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CompanyStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    HIDDEN = "hidden"
    TITLES = {
        PENDING: "🕓 На модерации", APPROVED: "✅ Одобрена", REJECTED: "❌ Отклонена",
        BLOCKED: "⛔ Заблокирована", HIDDEN: "🙈 Скрыта",
    }


class PaymentStatus:
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class StatEvent:
    IMPRESSION = "impression"      # показ в списках/поиске
    CARD_OPEN = "card_open"        # открытие карточки
    CONTACTS_OPEN = "contacts_open"
    FAVORITE_ADD = "favorite_add"
    REVIEW = "review"
    TG_CLICK = "tg_click"
    PHONE_CLICK = "phone_click"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256), default="")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # None — город ещё не спрашивали, "" — «любой город»
    city: Mapped[str | None] = mapped_column(String(120))

    company: Mapped["Company | None"] = relationship(back_populates="owner", uselist=False, passive_deletes=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    subcategories: Mapped[list["SubCategory"]] = relationship(back_populates="category", passive_deletes=True)


class SubCategory(Base):
    __tablename__ = "subcategories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[Category] = relationship(back_populates="subcategories")
    __table_args__ = (UniqueConstraint("category_id", "title", name="uq_subcategory_title"),)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    subcategory_id: Mapped[int | None] = mapped_column(ForeignKey("subcategories.id", ondelete="SET NULL"))

    name: Mapped[str] = mapped_column(String(120), index=True)
    short_description: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    services: Mapped[str] = mapped_column(Text, default="")
    materials: Mapped[str] = mapped_column(Text, default="")
    country: Mapped[str] = mapped_column(String(80), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    city_key: Mapped[str] = mapped_column(String(120), default="", index=True)  # нормализованный город для фильтра
    address: Mapped[str] = mapped_column(String(255), default="")
    work_hours: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(120))
    website: Mapped[str | None] = mapped_column(String(255))
    logo_file_id: Mapped[str | None] = mapped_column(String(256))
    photos: Mapped[list] = mapped_column(JSON, default=list)
    # Нормализованный (casefold) текст для регистронезависимого поиска, в т.ч. кириллицы в SQLite
    search_text: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default=CompanyStatus.PENDING, index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    tariff: Mapped[str | None] = mapped_column(String(16))
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="company")
    category: Mapped[Category] = relationship()
    subcategory: Mapped[SubCategory | None] = relationship()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_review_user_company"),)


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_favorite"),)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # company_id может стать NULL после удаления компании — история доходов сохраняется
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    tariff: Mapped[str] = mapped_column(String(16))
    months: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[int] = mapped_column(Integer)  # в рублях (целое)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PENDING, index=True)
    provider: Mapped[str] = mapped_column(String(16), default="manual")  # telegram | manual | admin
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    tariff: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    payment_id: Mapped[int | None] = mapped_column(Integer)


class Statistic(Base):
    __tablename__ = "statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_statistics_company_event", "company_id", "event"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """Настройки бота, редактируемые из админ-панели (тексты «О проекте», «Поддержка» и т. д.)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
