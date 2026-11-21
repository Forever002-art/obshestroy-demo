"""Конфигурация проекта: переменные окружения и тарифы."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class Tariff:
    """Описание тарифа подписки."""

    code: str
    title: str
    price: int  # рублей за месяц
    mark: str  # отметка в каталоге
    max_photos: int
    priority: int  # чем больше, тем выше в выдаче
    features: tuple[str, ...]


TARIFFS: dict[str, Tariff] = {
    "standard": Tariff(
        "standard", "Стандарт", 1500, "", 3, 1,
        ("размещение в каталоге", "поиск", "до 3 фотографий"),
    ),
    "premium": Tariff(
        "premium", "Премиум", 2500, "⭐", 8, 2,
        ("всё из тарифа «Стандарт»", "выше в поиске", "отметка ⭐", "до 8 фотографий"),
    ),
    "vip": Tariff(
        "vip", "VIP", 4000, "👑", 15, 3,
        ("всё из тарифа «Премиум»", "всегда первым в списках", "отметка 👑",
         "отдельный раздел «VIP»", "максимальный приоритет в поиске", "до 15 фотографий"),
    ),
}
TRIAL_TARIFF = "standard"  # тариф пробного периода
MONTH_OPTIONS: tuple[int, ...] = (1, 3, 6, 12)
SUBSCRIPTION_DAYS_PER_MONTH = 30


def _parse_ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(";", ",").split(",") if x.strip().lstrip("-").isdigit())


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _sqlite_file(url: URL) -> Path | None:
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    if _bool(url.query.get("uri"), False):
        return None
    return (BASE_DIR / url.database).resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_url: URL
    auto_migrate: bool
    payment_provider_token: str
    currency: str
    payment_instructions: str
    support_username: str
    timezone: str
    backup_dir: Path
    log_dir: Path
    backups_keep: int
    trial_days: int
    dadata_token: str
    proxy_url: str
    demo_mode: bool
    page_size: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и заполните его.")
        database_url = make_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db"))
        if database_url.drivername in {"postgres", "postgresql"}:
            database_url = database_url.set(drivername="postgresql+psycopg")
        sqlite_file = _sqlite_file(database_url)
        if sqlite_file is not None:
            database_url = database_url.set(database=str(sqlite_file))
        return cls(
            bot_token=token,
            admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
            database_url=database_url,
            auto_migrate=_bool(os.getenv("AUTO_MIGRATE"), True),
            payment_provider_token=os.getenv("PAYMENT_PROVIDER_TOKEN", "").strip(),
            currency=os.getenv("CURRENCY", "RUB"),
            payment_instructions=os.getenv("PAYMENT_INSTRUCTIONS", "Свяжитесь с поддержкой для оплаты."),
            support_username=os.getenv("SUPPORT_USERNAME", "@support"),
            timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
            backup_dir=(BASE_DIR / os.getenv("BACKUP_DIR", "./backups")).resolve(),
            log_dir=(BASE_DIR / os.getenv("LOG_DIR", "./logs")).resolve(),
            backups_keep=int(os.getenv("BACKUPS_KEEP", "7")),
            trial_days=int(os.getenv("TRIAL_DAYS", "60")),
            dadata_token=os.getenv("DADATA_TOKEN", "").strip(),
            proxy_url=os.getenv("PROXY_URL", "").strip(),
            demo_mode=_bool(os.getenv("DEMO_MODE"), True),
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.get_backend_name() == "sqlite"

    @property
    def sqlite_path(self) -> Path | None:
        """Путь к файлу для резервного копирования SQLite."""
        return _sqlite_file(self.database_url)

    @property
    def payments_enabled(self) -> bool:
        return not self.demo_mode and bool(self.payment_provider_token)


settings = Settings.from_env()
