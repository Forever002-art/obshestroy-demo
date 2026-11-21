"""Экспорт данных в Excel."""
from __future__ import annotations

import asyncio
import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy.ext.asyncio import AsyncSession

from repositories import companies as company_repo
from repositories import users as user_repo
from utils.formatting import fmt_dt


def _build(title: str, headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    for i, header in enumerate(headers, 1):
        width = max([len(str(header))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 50)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def users_xlsx(s: AsyncSession) -> bytes:
    users = await user_repo.all_users(s)
    rows = [[u.id, u.tg_id, u.username or "", u.full_name, "да" if u.is_blocked else "нет",
             fmt_dt(u.created_at, True), fmt_dt(u.last_active_at, True)] for u in users]
    return await asyncio.to_thread(_build, "Пользователи",
                                   ["ID", "Telegram ID", "Username", "Имя", "Заблокирован", "Регистрация",
                                    "Последняя активность"], rows)


async def companies_xlsx(s: AsyncSession) -> bytes:
    companies = await company_repo.all_companies(s)
    rows = [[c.id, c.name, c.category.title if c.category else "", c.status, c.tariff or "",
             fmt_dt(c.subscription_until, True), c.country, c.region, c.city, c.address, c.phone or "",
             c.telegram or "", c.email or "", c.website or "", c.views, fmt_dt(c.created_at, True)]
            for c in companies]
    return await asyncio.to_thread(_build, "Компании",
                                   ["ID", "Название", "Категория", "Статус", "Тариф", "Подписка до", "Страна",
                                    "Регион", "Город", "Адрес", "Телефон", "Telegram", "Email", "Сайт",
                                    "Просмотры", "Регистрация"], rows)
