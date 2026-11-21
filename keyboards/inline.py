"""Inline-клавиатуры."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Markup

from config import MONTH_OPTIONS, TARIFFS
from utils.cities import POPULAR_CITIES
from models import Category, Company, CompanyStatus, SubCategory, User
from services.company_service import CONTACT_FIELDS, FIELDS
from utils.formatting import truncate

NOOP = "noop"


def _kb(rows: list[list[Btn]]) -> Markup:
    return Markup(inline_keyboard=rows)


def _b(text: str, data: str) -> Btn:
    return Btn(text=text, callback_data=data)


def _chunk(buttons: list[Btn], size: int = 2) -> list[list[Btn]]:
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def pagination(prefix: str, page: int, pages: int) -> list[Btn]:
    """Строка пагинации; callback = '<prefix>:<номер страницы>'."""
    if pages <= 1:
        return []
    row = []
    row.append(_b("◀️", f"{prefix}:{page - 1}") if page > 0 else _b("·", NOOP))
    row.append(_b(f"{page + 1}/{pages}", NOOP))
    row.append(_b("▶️", f"{prefix}:{page + 1}") if page < pages - 1 else _b("·", NOOP))
    return row


# ---------- Общие ----------
def cancel_kb(data: str = "reg:cancel") -> Markup:
    return _kb([[_b("❌ Отмена", data)]])


def skip_cancel_kb(skip: str = "reg:skip", cancel: str = "reg:cancel") -> Markup:
    return _kb([[_b("⏭ Пропустить", skip), _b("❌ Отмена", cancel)]])


def back_kb(data: str, text: str = "⬅ Назад") -> Markup:
    return _kb([[_b(text, data)]])


def home_kb(is_admin: bool, has_company: bool, city: str | None = None) -> Markup:
    rows = [
        [_b("🔎 Каталог", "cat"), _b("👑 VIP", "vip:0")],
        [_b(f"📍 Город: {city or 'любой'}", "city:change")],
        [_b("🏢 Личный кабинет", "cab") if has_company else _b("➕ Зарегистрировать компанию", "reg:start")],
    ]
    if is_admin:
        rows.append([_b("🛠 Админ-панель", "a:menu")])
    return _kb(rows)


# ---------- Каталог ----------
def categories_kb(cats: list[Category]) -> Markup:
    rows = [[_b("🔍 Не знаете раздел? Найти по виду работ", "search:start")]]
    rows += _chunk([_b(c.title, f"c:{c.id}") for c in cats])
    rows.append([_b("👑 VIP-раздел", "vip:0")])
    return _kb(rows)


def subcategories_kb(cat_id: int, subs: list[SubCategory]) -> Markup:
    rows = [[_b("📋 Все компании категории", f"cl:{cat_id}:0:0")]]
    rows += _chunk([_b(s.title, f"cl:{cat_id}:{s.id}:0") for s in subs])
    rows.append([_b("⬅ К категориям", "cat")])
    return _kb(rows)


def list_kb(companies: list[Company], prefix: str, page: int, pages: int, back_cb: str,
            extra: list[list[Btn]] | None = None) -> Markup:
    """Список компаний. Кнопка компании несёт «адрес возврата» (prefix:page)."""
    rows = []
    for c in companies:
        mark = {"vip": "👑 ", "premium": "⭐ "}.get(c.tariff or "", "")
        label = truncate(f"{mark}{c.name} · {c.city}" if c.city else f"{mark}{c.name}", 60)
        rows.append([_b(label, f"co:{c.id}:{prefix}:{page}")])
    nav = pagination(prefix, page, pages)
    if nav:
        rows.append(nav)
    rows += extra or []
    rows.append([_b("⬅ Назад", back_cb)])
    return _kb(rows)


def category_rows(cats: list[Category]) -> list[list[Btn]]:
    """Подсказки разделов под результатами поиска (до 3 штук)."""
    return [[_b(f"📂 {c.title}", f"c:{c.id}")] for c in cats[:3]]


def empty_kb(back_cb: str, show_city: bool, extra: list[list[Btn]] | None = None) -> Markup:
    rows = list(extra or [])
    if show_city:
        rows.append([_b("📍 Сменить город", "city:change")])
    rows.append([_b("⬅ Назад", back_cb)])
    return _kb(rows)


def city_kb() -> Markup:
    rows = _chunk([_b(c, f"city:set:{i}") for i, c in enumerate(POPULAR_CITIES)])
    rows.append([_b("🌍 Любой город", "city:any")])
    return _kb(rows)


def lookup_kb(hints: list[dict]) -> Markup:
    """Варианты организаций из реестра для автозаполнения."""
    rows = [[_b(truncate(f"{h['name']} · {h['city'] or h['region'] or '—'}", 60), f"lk:{i}")] for i, h in enumerate(hints)]
    rows.append([_b("✏ Моей компании нет в списке", "lk:none")])
    rows.append([_b("❌ Отмена", "reg:cancel")])
    return _kb(rows)


def card_kb(company_id: int, back: str, is_fav: bool, has_photos: bool) -> Markup:
    fav = _b("💔 Убрать из избранного" if is_fav else "❤️ Добавить в избранное", f"fv:{company_id}:{back}")
    rows = [
        [fav],
        [_b("⭐ Оставить отзыв", f"rv:{company_id}:{back}"), _b("💬 Отзывы", f"rl:{company_id}:{back}")],
        [_b("📞 Показать контакты", f"ct:{company_id}:{back}")],
    ]
    if has_photos:
        rows.append([_b("📷 Фотографии", f"ph:{company_id}:{back}")])
    rows.append([_b("⬅ Назад", back)])
    return _kb(rows)


def contacts_kb(company: Company, back: str) -> Markup:
    rows = []
    row = []
    if company.telegram:
        row.append(_b("✈️ Написать в Telegram", f"tg:{company.id}"))
    if company.phone:
        row.append(_b("☎️ Показать номер", f"pn:{company.id}"))
    if row:
        rows.append(row)
    rows.append([_b("⬅ Назад", f"co:{company.id}:{back}")])
    return _kb(rows)


def rating_kb(company_id: int, back: str) -> Markup:
    rows = [[_b("⭐" * n, f"rt:{company_id}:{n}") for n in (1, 2, 3)], [_b("⭐" * n, f"rt:{company_id}:{n}") for n in (4, 5)]]
    rows.append([_b("❌ Отмена", f"co:{company_id}:{back}")])
    return _kb(rows)


# ---------- Выбор категории (универсально: регистрация / редактирование / админ) ----------
def pick_categories_kb(cats: list[Category], prefix: str, cancel: str) -> Markup:
    rows = _chunk([_b(c.title, f"{prefix}:{c.id}") for c in cats])
    rows.append([_b("❌ Отмена", cancel)])
    return _kb(rows)


def pick_subs_kb(subs: list[SubCategory], prefix: str, cancel: str) -> Markup:
    rows = _chunk([_b(s.title, f"{prefix}:{s.id}") for s in subs])
    rows.append([_b("❌ Отмена", cancel)])
    return _kb(rows)


def confirm_registration_kb() -> Markup:
    return _kb([[_b("✅ Отправить заявку", "reg:send")], [_b("❌ Отмена", "reg:cancel")]])


def photos_done_kb(done: str = "reg:photos_done", cancel: str = "reg:cancel") -> Markup:
    return _kb([[_b("✅ Готово", done), _b("❌ Отмена", cancel)]])


# ---------- Личный кабинет ----------
def cabinet_kb(company: Company) -> Markup:
    rows = [[_b("🏢 Моя компания", "cab:company"), _b("✏ Редактировать информацию", "cab:edit")]]
    if company.status == CompanyStatus.REJECTED:
        rows.append([_b("🔁 Подать заявку заново", "reg:start")])
    rows += [
        [_b("📷 Фотографии", "cab:photos"), _b("📞 Контакты", "cab:contacts")],
        [_b("📊 Статистика", "cab:stats"), _b("💳 Подписка", "cab:sub")],
        [_b("⭐ Отзывы", "cab:reviews")],
        [_b("⬅ Главная", "home")],
    ]
    return _kb(rows)


def fields_kb(keys: list[str], make_cb, back_cb: str, extra: list[list[Btn]] | None = None) -> Markup:
    """Кнопки редактирования полей. make_cb(key) -> callback_data."""
    rows = _chunk([_b(FIELDS[k].title if k != "category" else "Категория", make_cb(k)) for k in keys])
    rows += extra or []
    rows.append([_b("⬅ Назад", back_cb)])
    return _kb(rows)


EDIT_KEYS = ["name", "category", "description", "services", "materials", "country", "region", "city",
             "address", "work_hours"]
CONTACT_KEYS = list(CONTACT_FIELDS)


def photos_menu_kb(back: str = "cab") -> Markup:
    return _kb([
        [_b("➕ Добавить фото", "ph_add"), _b("🖼 Сменить логотип", "ph_logo")],
        [_b("🗑 Удалить последнее", "ph_last"), _b("🧹 Удалить все", "ph_clear")],
        [_b("⬅ Назад", back)],
    ])


def cab_back_kb() -> Markup:
    return back_kb("cab")


# ---------- Подписка / оплата ----------
def tariffs_kb() -> Markup:
    rows = [[_b(f"{t.mark} {t.title} — {t.price} ₽/мес".strip(), f"sub:{t.code}")] for t in TARIFFS.values()]
    rows.append([_b("⬅ Назад", "cab")])
    return _kb(rows)


def months_kb(tariff: str) -> Markup:
    price = TARIFFS[tariff].price
    rows = _chunk([_b(f"{m} мес. — {price * m} ₽", f"buy:{tariff}:{m}") for m in MONTH_OPTIONS])
    rows.append([_b("⬅ Назад", "cab:sub")])
    return _kb(rows)


def manual_pay_kb(payment_id: int) -> Markup:
    return _kb([[_b("✅ Я оплатил", f"paid:{payment_id}")], [_b("❌ Отменить", f"payx:{payment_id}")]])


def admin_payment_kb(payment_id: int) -> Markup:
    return _kb([[_b("✅ Подтвердить", f"a:pay:{payment_id}:ok"), _b("❌ Отклонить", f"a:pay:{payment_id}:no")]])


# ---------- Админ-панель ----------
def admin_menu_kb() -> Markup:
    return _kb([
        [_b("🆕 Новые заявки", "a:new:0"), _b("🏢 Все компании", "a:cl:all:0")],
        [_b("👥 Все пользователи", "a:ul:0"), _b("💰 Доход", "a:inc")],
        [_b("✅ Активные подписки", "a:subs:0"), _b("⭐ Отзывы", "a:rev:0")],
        [_b("✏ Редактирование компаний", "a:cl:edit:0"), _b("🗑 Удаление компаний", "a:cl:del:0")],
        [_b("⛔ Блокировка компаний", "a:cl:block:0"), _b("👤 Блокировка пользователей", "a:ul:0")],
        [_b("⏳ Продление подписок", "a:cl:ext:0"), _b("📊 Статистика", "a:stat")],
        [_b("📣 Рассылка пользователям", "a:bc:users"), _b("📣 Рассылка компаниям", "a:bc:companies")],
        [_b("📥 Excel: пользователи", "a:xu"), _b("📥 Excel: компании", "a:xc")],
        [_b("💾 Резервная копия БД", "a:bk"), _b("♻️ Восстановление БД", "a:rs")],
        [_b("⚙ Настройки", "a:set")],
        [_b("⬅ Главная", "home")],
    ])


def admin_list_kb(items: list[tuple[str, str]], prefix: str, page: int, pages: int, back: str = "a:menu") -> Markup:
    """items: [(текст, callback)]."""
    rows = [[_b(truncate(t, 60), cb)] for t, cb in items]
    nav = pagination(prefix, page, pages)
    if nav:
        rows.append(nav)
    rows.append([_b("⬅ В админ-панель", back)])
    return _kb(rows)


_STATUS_EMOJI = {"pending": "🕓", "approved": "✅", "rejected": "❌", "blocked": "⛔", "hidden": "🙈"}


def company_label(c: Company) -> str:
    return f"{_STATUS_EMOJI.get(c.status, '')} #{c.id} {c.name}"


def admin_company_kb(c: Company, mode: str, back: str) -> Markup:
    """Кнопки зависят от режима раздела (mode): all/edit/del/block/ext/new."""
    show = lambda *modes: mode in ("all", "new", *modes)  # noqa: E731
    rows: list[list[Btn]] = []
    if c.status == CompanyStatus.PENDING and show():
        rows.append([_b("✅ Одобрить", f"a:ok:{c.id}"), _b("❌ Отклонить", f"a:no:{c.id}")])
    if show("edit"):
        rows.append([_b("✏ Редактировать данные", f"a:edit:{c.id}")])
    if show("block"):
        rows.append([_b("✅ Разблокировать" if c.status == CompanyStatus.BLOCKED else "⛔ Заблокировать", f"a:blk:{c.id}"),
                     _b("👁 Показать" if c.status == CompanyStatus.HIDDEN else "🙈 Скрыть", f"a:hid:{c.id}")])
    if show("ext"):
        rows.append([_b("⏳ Продлить подписку", f"a:ext:{c.id}")])
    if show("del"):
        rows.append([_b("🗑 Удалить компанию", f"a:del:{c.id}")])
    rows.append([_b("⬅ Назад", back)])
    return _kb(rows)


def admin_ext_kb(company_id: int) -> Markup:
    rows = []
    for t in TARIFFS.values():
        rows.append([_b(f"{t.mark} {t.title}: {m} мес.".strip(), f"a:extdo:{company_id}:{t.code}:{m}") for m in (1, 3)])
    rows.append([_b("⬅ Назад", f"a:c:{company_id}:ext")])
    return _kb(rows)


def admin_confirm_delete_kb(company_id: int) -> Markup:
    return _kb([[_b("🗑 Да, удалить", f"a:delyes:{company_id}"), _b("↩ Нет", f"a:c:{company_id}:del")]])


def admin_user_kb(u: User, page: int) -> Markup:
    return _kb([[_b("✅ Разблокировать" if u.is_blocked else "⛔ Заблокировать", f"a:ub:{u.id}:{page}")],
                [_b("⬅ Назад", f"a:ul:{page}")]])


def admin_review_kb(reviews: list, page: int, pages: int) -> Markup:
    rows = _chunk([_b(f"🗑 Удалить №{r.id}", f"a:rd:{r.id}:{page}") for r in reviews], 2)
    nav = pagination("a:rev", page, pages)
    if nav:
        rows.append(nav)
    rows.append([_b("⬅ В админ-панель", "a:menu")])
    return _kb(rows)


def broadcast_confirm_kb() -> Markup:
    return _kb([[_b("📣 Отправить", "a:bcgo"), _b("❌ Отмена", "a:bcx")]])


def admin_settings_kb() -> Markup:
    return _kb([[_b("ℹ️ Текст «О проекте»", "a:sv:about_text")],
                [_b("📞 Текст «Поддержка»", "a:sv:support_text")],
                [_b("👋 Приветствие", "a:sv:welcome_text")],
                [_b("⬅ В админ-панель", "a:menu")]])
