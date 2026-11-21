"""Резервное копирование и восстановление SQLite-базы."""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from config import settings
from database import engine
from utils.logging_setup import admin_log


class BackupError(Exception):
    """Ошибка резервного копирования/восстановления."""


def _require_sqlite() -> Path:
    path = settings.sqlite_path
    if path is None:
        raise BackupError("Для PostgreSQL используйте pg_dump / pg_restore — встроенный бэкап работает только с SQLite.")
    return path


def _copy_sync(src: Path, dst: Path) -> None:
    """Консистентная копия через sqlite3 backup API."""
    with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
        source.backup(target)


async def create_backup(prefix: str = "backup") -> Path:
    src = _require_sqlite()
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    dst = settings.backup_dir / f"{prefix}_{datetime.now(settings.tz):%Y%m%d_%H%M%S}.db"
    await asyncio.to_thread(_copy_sync, src, dst)
    await asyncio.to_thread(rotate)
    admin_log.info("Создана резервная копия %s", dst.name)
    return dst


def rotate() -> None:
    """Оставляет только последние N автоматических копий."""
    files = sorted(settings.backup_dir.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[settings.backups_keep:]:
        old.unlink(missing_ok=True)


def _validate(path: Path) -> None:
    try:
        with sqlite3.connect(path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise BackupError("Файл не является базой SQLite.") from exc
    if not {"users", "companies", "categories"} <= tables:
        raise BackupError("В файле нет таблиц проекта (users, companies, categories).")


async def restore_backup(uploaded: Path) -> None:
    """Заменяет текущую БД загруженным файлом (предварительно делает страховочную копию)."""
    target = _require_sqlite()
    await asyncio.to_thread(_validate, uploaded)
    await create_backup(prefix="before_restore")
    await engine.dispose()  # закрываем соединения перед подменой файла
    for suffix in ("-wal", "-shm"):
        Path(str(target) + suffix).unlink(missing_ok=True)
    # Копируем во временный файл и атомарно подменяем (новый inode — открытые соединения не повредятся)
    tmp = target.with_suffix(".restore_tmp")
    await asyncio.to_thread(shutil.copyfile, uploaded, tmp)
    await asyncio.to_thread(os.replace, tmp, target)
    admin_log.warning("База данных восстановлена из файла %s", uploaded.name)
