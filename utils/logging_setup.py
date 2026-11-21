"""Настройка логирования: консоль + ротируемые файлы по темам."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import settings

_FMT = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")


def _file_handler(name: str, level: int = logging.INFO) -> RotatingFileHandler:
    handler = RotatingFileHandler(settings.log_dir / name, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(_FMT)
    handler.setLevel(level)
    return handler


def setup_logging() -> None:
    """Файлы: bot.log (всё), errors.log (ошибки), admin.log, payments.log, registration.log, company.log."""
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(_FMT)
    root.addHandler(console)
    root.addHandler(_file_handler("bot.log"))
    root.addHandler(_file_handler("errors.log", logging.ERROR))
    for topic in ("admin", "payments", "registration", "company"):
        logging.getLogger(f"bot.{topic}").addHandler(_file_handler(f"{topic}.log"))
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


admin_log = logging.getLogger("bot.admin")
payment_log = logging.getLogger("bot.payments")
registration_log = logging.getLogger("bot.registration")
company_log = logging.getLogger("bot.company")
