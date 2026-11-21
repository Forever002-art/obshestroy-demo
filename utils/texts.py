"""Текстовые шаблоны: карточка компании, статистика и т. д."""
from __future__ import annotations

from config import TARIFFS
from models import Company, CompanyStatus, StatEvent, utcnow
from utils.formatting import dash, esc, fmt_dt, stars, truncate

CAPTION_LIMIT = 1024  # лимит подписи к фото в Telegram


def tariff_mark(company: Company) -> str:
    tariff = TARIFFS.get(company.tariff or "")
    return f"{tariff.mark} " if tariff and tariff.mark else ""


def public_status(company: Company) -> str:
    if company.status == CompanyStatus.APPROVED and company.subscription_until and company.subscription_until > utcnow():
        return "✅ Активна"
    return CompanyStatus.TITLES.get(company.status, company.status)


def _card(company: Company, rating: tuple[float, int], max_text: int) -> str:
    avg, cnt = rating
    cat = company.category.title if company.category else "—"
    if company.subcategory:
        cat += f" → {company.subcategory.title}"
    rate = f"{stars(avg)} {avg:.1f}" if cnt else "нет оценок"
    parts = [
        f"{tariff_mark(company)}<b>{esc(company.name)}</b>",
        f"<i>{esc(company.short_description)}</i>" if company.short_description else "",
        "",
        f"🏷 <b>Категория:</b> {esc(cat)}",
        f"⭐ <b>Рейтинг:</b> {rate} · отзывов: {cnt}",
        f"👁 <b>Просмотров:</b> {company.views}",
        "",
        f"📝 <b>Описание:</b>\n{dash(truncate(company.description, max_text))}",
        f"🛠 <b>Услуги:</b>\n{dash(truncate(company.services, max_text))}",
        f"🧱 <b>Материалы:</b>\n{dash(truncate(company.materials, max_text))}",
        "",
        f"🌍 <b>Страна:</b> {dash(company.country)}",
        f"🗺 <b>Регион:</b> {dash(company.region)}",
        f"🏙 <b>Город:</b> {dash(company.city)}",
        f"📍 <b>Адрес:</b> {dash(company.address)}",
        f"🕒 <b>График работы:</b> {dash(company.work_hours)}",
        "",
        f"📞 <b>Телефон:</b> {dash(company.phone)}",
        f"✈️ <b>Telegram:</b> {dash(company.telegram)}",
        f"✉️ <b>Email:</b> {dash(company.email)}",
        f"🌐 <b>Сайт:</b> {dash(company.website)}",
        "",
        f"📅 <b>Дата регистрации:</b> {fmt_dt(company.created_at)}",
        f"⏳ <b>Подписка до:</b> {fmt_dt(company.subscription_until)}",
        f"📌 <b>Статус:</b> {public_status(company)}",
    ]
    return "\n".join(parts)


def company_card(company: Company, rating: tuple[float, int], with_photo: bool) -> str:
    """Текст карточки. Если карточка отправляется подписью к фото — укладываемся в 1024 символа."""
    limits = (700, 350, 180, 90, 40) if with_photo else (1200,)
    text = ""
    for lim in limits:
        text = _card(company, rating, lim)
        if not with_photo or len(text) <= CAPTION_LIMIT:
            return text
    return text[: CAPTION_LIMIT - 1] + "…"


def contacts_text(company: Company) -> str:
    return (
        f"📞 <b>Контакты — {esc(company.name)}</b>\n\n"
        f"<b>Телефон</b>\n{dash(company.phone)}\n\n"
        f"<b>Telegram</b>\n{dash(company.telegram)}\n\n"
        f"<b>Email</b>\n{dash(company.email)}\n\n"
        f"<b>Сайт</b>\n{dash(company.website)}"
    )


def stats_text(company: Company, counts: dict[str, int], reviews: int) -> str:
    return (
        f"📊 <b>Статистика — {esc(company.name)}</b>\n\n"
        f"👁 Просмотры (показы в каталоге и поиске): <b>{counts.get(StatEvent.IMPRESSION, 0)}</b>\n"
        f"📖 Открытия карточки: <b>{counts.get(StatEvent.CARD_OPEN, 0)}</b>\n"
        f"📞 Открытия контактов: <b>{counts.get(StatEvent.CONTACTS_OPEN, 0)}</b>\n"
        f"❤️ Добавления в избранное: <b>{counts.get(StatEvent.FAVORITE_ADD, 0)}</b>\n"
        f"⭐ Количество отзывов: <b>{reviews}</b>\n"
        f"✈️ Переходы в Telegram: <b>{counts.get(StatEvent.TG_CLICK, 0)}</b>\n"
        f"☎️ Нажатия на телефон: <b>{counts.get(StatEvent.PHONE_CLICK, 0)}</b>"
    )


def subscription_text(company: Company) -> str:
    tariff = TARIFFS.get(company.tariff or "")
    active = bool(company.subscription_until and company.subscription_until > utcnow())
    if not tariff:
        return "💳 <b>Подписка</b>\n\nПодписка не оформлена. Компания не отображается в каталоге."
    left = ""
    if active:
        days = (company.subscription_until - utcnow()).days
        left = f"\nОсталось: <b>{days} дн.</b>"
    return (
        f"💳 <b>Подписка</b>\n\nТариф: <b>{tariff.mark} {tariff.title}</b>\n"
        f"Статус: {'✅ активна' if active else '⌛ истекла'}\n"
        f"Действует до: <b>{fmt_dt(company.subscription_until, True)}</b>{left}"
    )


def tariffs_text() -> str:
    lines = ["💳 <b>Тарифы</b>\n"]
    for t in TARIFFS.values():
        feats = "\n".join(f"  • {f}" for f in t.features)
        lines.append(f"<b>{t.mark} {t.title} — {t.price} ₽/мес</b>\n{feats}\n")
    return "\n".join(lines)
