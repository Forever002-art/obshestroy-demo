"""Хендлеры обычного пользователя: каталог, поиск, карточки, избранное, отзывы."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from config import settings
from keyboards import inline as ikb
from keyboards.reply import (BTN_ABOUT, BTN_CATALOG, BTN_FAVORITES, BTN_HOME, BTN_SEARCH, BTN_SUPPORT,
                             main_menu_kb)
from models import Company, CompanyStatus, StatEvent, User, utcnow
from repositories import categories as cat_repo
from repositories import companies as company_repo
from repositories import favorites as fav_repo
from repositories import reviews as review_repo
from repositories import system as system_repo
from repositories import users as user_repo
from services import statistics_service as stats
from services.notification_service import NotificationService, t_new_review
from states.states import CityStates, ReviewStates, SearchStates
from utils import texts
from utils.cities import POPULAR_CITIES
from utils.formatting import esc, fmt_dt, normalize, pages_count, stars, stem, truncate
from utils.keywords import categories_for
from utils.ui import keyboard_needed, render, toast

router = Router(name="user")
PAGE = settings.page_size


# ======================= Вспомогательные =======================
def _city_filter(user: User) -> str | None:
    """Основа названия города пользователя для фильтра каталога (None — любой город)."""
    return stem(normalize(user.city)) if user.city else None


def _city_title(user: User) -> str:
    return f" · 📍 {esc(user.city)}" if user.city else ""


async def _home(event: Message | CallbackQuery, s: AsyncSession, user: User, is_admin: bool) -> None:
    has_company = await company_repo.get_by_owner(s, user.id) is not None
    text = await system_repo.get_setting(s, "welcome_text")
    await render(event, text, ikb.home_kb(is_admin, has_company, user.city))


async def _categories(event: Message | CallbackQuery, s: AsyncSession) -> None:
    cats = await cat_repo.all_categories(s)
    await render(event, "🔎 <b>Каталог</b>\n\nВыберите категорию или найдите по виду работ:", ikb.categories_kb(cats))


async def _show_list(event, s: AsyncSession, user: User, *, title: str, items: list[Company], total: int,
                     page: int, prefix: str, back_cb: str, empty: str, extra=None) -> None:
    """Универсальный экран списка компаний с пагинацией."""
    if not items:
        note = f"\n📍 Поиск ведётся по городу «{esc(user.city)}»." if user.city else ""
        await render(event, f"{title}\n\n{empty}{note}", ikb.empty_kb(back_cb, bool(user.city), extra))
        return
    await stats.record_many(s, items, StatEvent.IMPRESSION, user.id)
    pages = pages_count(total, PAGE)
    await render(event, f"{title}\n\nНайдено: <b>{total}</b>. Выберите компанию:",
                 ikb.list_kb(items, prefix, page, pages, back_cb, extra))


async def _catalog_list(event, s, user, cat_id: int, sub_id: int, page: int) -> None:
    cat = await cat_repo.get_category(s, cat_id)
    if cat is None:
        return
    items, total = await company_repo.catalog_page(s, category_id=cat_id, subcategory_id=sub_id or None,
                                                   city=_city_filter(user), offset=page * PAGE, limit=PAGE)
    title = f"<b>{esc(cat.title)}</b>"
    if sub_id:
        sub = await cat_repo.get_subcategory(s, sub_id)
        title += f" → {esc(sub.title) if sub else ''}"
    back = f"c:{cat_id}" if sub_id else "cat"
    await _show_list(event, s, user, title=title + _city_title(user), items=items, total=total, page=page,
                     prefix=f"cl:{cat_id}:{sub_id}", back_cb=back, empty="Пока нет компаний в этом разделе.")


async def _vip_list(event, s, user, page: int) -> None:
    items, total = await company_repo.catalog_page(s, tariff="vip", city=_city_filter(user),
                                                   offset=page * PAGE, limit=PAGE)
    await _show_list(event, s, user, title="👑 <b>VIP-компании</b>" + _city_title(user), items=items, total=total,
                     page=page, prefix="vip", back_cb="cat", empty="Пока нет VIP-компаний.")


async def _fav_list(event, s, user, page: int) -> None:
    items, total = await fav_repo.page(s, user.id, page * PAGE, PAGE)
    await _show_list(event, s, user, title="⭐ <b>Избранное</b>", items=items, total=total, page=page,
                     prefix="fav", back_cb="home", empty="Здесь пока пусто. Добавляйте компании кнопкой ❤️ в карточке.")


async def _search_results(event, s, user, query: str, page: int) -> None:
    """Поиск: слова ищутся в тексте компаний, а виды работ («штукатурка») ещё и ведут в нужный раздел."""
    cats = {c.title: c for c in await cat_repo.all_categories(s)}
    groups: list[tuple[str, list[int]]] = []
    suggested: dict[int, object] = {}
    for raw in normalize(query).split():
        found = [cats[t] for t in categories_for(raw) if t in cats]
        groups.append((stem(raw), [c.id for c in found]))
        for c in found:
            suggested.setdefault(c.id, c)
    hint_rows = ikb.category_rows(list(suggested.values()))
    items, total = await company_repo.catalog_page(s, tokens=groups, city=_city_filter(user),
                                                   offset=page * PAGE, limit=PAGE)
    if not total:
        note = f"\n📍 Поиск ведётся по городу «{esc(user.city)}»." if user.city else ""
        hint = "\n\nВозможно, вам подойдёт раздел:" if hint_rows else ""
        await render(event, f"По вашему запросу ничего не найдено.{note}{hint}",
                     ikb.empty_kb("home", bool(user.city), hint_rows))
        return
    title = f"🔍 <b>Результаты:</b> «{esc(truncate(query, 40))}»{_city_title(user)}"
    if hint_rows:
        title += "\n📂 Раздел по вашему запросу — кнопка ниже."
    await _show_list(event, s, user, title=title, items=items, total=total, page=page, prefix="sp",
                     back_cb="home", empty="", extra=hint_rows)


async def show_card(event, s: AsyncSession, user: User, is_admin: bool, company_id: int, back: str,
                    count: bool = True) -> None:
    """Показывает карточку компании (фото-логотип + подпись, если логотип загружен)."""
    company = await company_repo.get(s, company_id)
    is_owner = company is not None and company.owner_id == user.id
    visible = company is not None and company.status == CompanyStatus.APPROVED and bool(
        company.subscription_until and company.subscription_until > utcnow())
    if company is None or not (visible or is_owner or is_admin):
        if isinstance(event, CallbackQuery):
            await event.answer("Компания недоступна.", show_alert=True)
        return
    if count and not is_owner:
        await company_repo.increment_views(s, company.id)
        await stats.record(s, company.id, StatEvent.CARD_OPEN, user.id)
        set_committed_value(company, "views", company.views + 1)  # локально, без повторного UPDATE
    rating = await review_repo.rating(s, company.id)
    text = texts.company_card(company, rating, bool(company.logo_file_id))
    is_fav = await fav_repo.exists(s, user.id, company.id)
    await render(event, text, ikb.card_kb(company.id, back, is_fav, bool(company.photos)), company.logo_file_id)


# ======================= Команды и меню =======================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    await state.clear()
    if await keyboard_needed(message):  # нижняя клавиатура показывается один раз
        await message.answer("👋 Здравствуйте! Меню доступно внизу экрана.", reply_markup=main_menu_kb())
    if db_user.city is None:  # город ещё не выбирали
        await _ask_city(message, state)
    else:
        await _home(message, session, db_user, is_admin)


@router.message(F.text == BTN_HOME)
async def menu_home(message: Message, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    await state.clear()
    await _home(message, session, db_user, is_admin)


@router.message(F.text == BTN_CATALOG)
async def menu_catalog(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await _categories(message, session)


async def _prompt_search(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchStates.query)
    await render(event, "🔍 <b>Поиск</b>\n\nНапишите, что нужно: название компании, вид работ или материал.\n"
                        "Например: <i>штукатурка</i>, <i>натяжные потолки</i>, <i>кирпич</i>, <i>электрик</i>, "
                        "<i>окна</i>.\n\nНе знаете, в каком разделе искать? Просто напишите вид работ — "
                        "бот подскажет раздел.", ikb.back_kb("home", "🏠 Главная"))


@router.message(F.text == BTN_SEARCH)
async def menu_search(message: Message, state: FSMContext) -> None:
    await _prompt_search(message, state)


@router.callback_query(F.data == "search:start")
async def cb_search_start(call: CallbackQuery, state: FSMContext) -> None:
    await _prompt_search(call, state)
    await call.answer()


@router.message(F.text == BTN_FAVORITES)
async def menu_favorites(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    await _fav_list(message, session, db_user, 0)


@router.message(F.text == BTN_ABOUT)
async def menu_about(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await render(message, await system_repo.get_setting(session, "about_text"), ikb.back_kb("home", "🏠 Главная"))


@router.message(F.text == BTN_SUPPORT)
async def menu_support(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    text = await system_repo.get_setting(session, "support_text")
    await render(message, f"📞 <b>Поддержка</b>\n\n{text}\n\nКонтакт: {esc(settings.support_username)}",
                 ikb.back_kb("home", "🏠 Главная"))


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "home")
async def cb_home(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    await state.clear()
    await _home(call, session, db_user, is_admin)
    await call.answer()


# ======================= Каталог =======================
@router.callback_query(F.data == "cat")
async def cb_categories(call: CallbackQuery, session: AsyncSession) -> None:
    await _categories(call, session)
    await call.answer()


@router.callback_query(F.data.regexp(r"^c:\d+$"))
async def cb_category(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    cat_id = int(call.data.split(":")[1])
    cat = await cat_repo.get_category(session, cat_id)
    subs = await cat_repo.subcategories(session, cat_id) if cat else []
    if subs:
        await render(call, f"<b>{esc(cat.title)}</b>\n\nВыберите подкатегорию:", ikb.subcategories_kb(cat_id, subs))
    else:
        await _catalog_list(call, session, db_user, cat_id, 0, 0)
    await call.answer()


@router.callback_query(F.data.regexp(r"^cl:\d+:\d+:\d+$"))
async def cb_catalog_list(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    _, cat, sub, page = call.data.split(":")
    await _catalog_list(call, session, db_user, int(cat), int(sub), int(page))
    await call.answer()


@router.callback_query(F.data.regexp(r"^vip:\d+$"))
async def cb_vip(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await _vip_list(call, session, db_user, int(call.data.split(":")[1]))
    await call.answer()


@router.callback_query(F.data.regexp(r"^fav:\d+$"))
async def cb_fav(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    await _fav_list(call, session, db_user, int(call.data.split(":")[1]))
    await call.answer()


# ======================= Поиск =======================
@router.message(SearchStates.query, F.text, ~F.text.startswith("/"))
async def search_query(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    query = message.text.strip()
    if len(query) < 2:
        await toast(message, "Введите хотя бы 2 символа.")
        return
    await state.update_data(q=query)
    await _search_results(message, session, db_user, query, 0)


@router.callback_query(F.data.regexp(r"^sp:\d+$"))
async def cb_search_page(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    query = (await state.get_data()).get("q")
    if not query:
        await call.answer("Запрос устарел — повторите поиск.", show_alert=True)
        return
    await _search_results(call, session, db_user, query, int(call.data.split(":")[1]))
    await call.answer()


# ======================= Карточка и действия =======================
def _parse(data: str) -> tuple[int, str]:
    """'xx:<company_id>:<back>' -> (company_id, back)."""
    _, cid, back = data.split(":", 2)
    return int(cid), back


@router.callback_query(F.data.startswith("co:"))
async def cb_company(call: CallbackQuery, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    cid, back = _parse(call.data)
    # повторный вход из «Назад» (контакты/отзывы) не накручивает просмотры
    await show_card(call, session, db_user, is_admin, cid, back)
    await call.answer()


@router.callback_query(F.data.startswith("fv:"))
async def cb_favorite(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    cid, back = _parse(call.data)
    company = await company_repo.get(session, cid)
    if company is None:
        await call.answer("Компания не найдена.", show_alert=True)
        return
    if await fav_repo.exists(session, db_user.id, cid):
        await fav_repo.remove(session, db_user.id, cid)
        is_fav, note = False, "Удалено из избранного"
    else:
        await fav_repo.add(session, db_user.id, cid)
        await stats.record(session, cid, StatEvent.FAVORITE_ADD, db_user.id)
        is_fav, note = True, "Добавлено в избранное ❤️"
    await call.message.edit_reply_markup(reply_markup=ikb.card_kb(cid, back, is_fav, bool(company.photos)))
    await call.answer(note)


@router.callback_query(F.data.startswith("ct:"))
async def cb_contacts(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    cid, back = _parse(call.data)
    company = await company_repo.get(session, cid)
    if company is None:
        await call.answer("Компания не найдена.", show_alert=True)
        return
    if company.owner_id != db_user.id:
        await stats.record(session, cid, StatEvent.CONTACTS_OPEN, db_user.id)
    await render(call, texts.contacts_text(company), ikb.contacts_kb(company, back))
    await call.answer()


@router.callback_query(F.data.startswith("tg:"))
async def cb_tg_click(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get(session, int(call.data.split(":")[1]))
    if company is None or not company.telegram:
        await call.answer("Контакт недоступен.", show_alert=True)
        return
    await stats.record(session, company.id, StatEvent.TG_CLICK, db_user.id)
    username = company.telegram.lstrip("@")
    await call.message.answer(f"✈️ <a href=\"https://t.me/{esc(username)}\">Открыть чат с @{esc(username)}</a>")
    await call.answer()


@router.callback_query(F.data.startswith("pn:"))
async def cb_phone_click(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get(session, int(call.data.split(":")[1]))
    if company is None or not company.phone:
        await call.answer("Контакт недоступен.", show_alert=True)
        return
    await stats.record(session, company.id, StatEvent.PHONE_CLICK, db_user.id)
    await call.answer(f"📞 {company.phone}", show_alert=True)


@router.callback_query(F.data.startswith("ph:"))
async def cb_photos(call: CallbackQuery, session: AsyncSession) -> None:
    cid, _ = _parse(call.data)
    company = await company_repo.get(session, cid)
    if company is None or not company.photos:
        await call.answer("Фотографий нет.", show_alert=True)
        return
    media = [InputMediaPhoto(media=f) for f in company.photos[:10]]
    await call.bot.send_media_group(call.from_user.id, media)
    await call.answer()


@router.callback_query(F.data.startswith("rl:"))
async def cb_reviews(call: CallbackQuery, session: AsyncSession) -> None:
    cid, back = _parse(call.data)
    company = await company_repo.get(session, cid)
    if company is None:
        await call.answer("Компания не найдена.", show_alert=True)
        return
    avg, cnt = await review_repo.rating(session, cid)
    lines = [f"💬 <b>Отзывы — {esc(company.name)}</b>",
             f"Средняя оценка: <b>{avg:.1f}</b> {stars(avg)} · отзывов: <b>{cnt}</b>\n" if cnt else "Отзывов пока нет.\n"]
    for review, author in await review_repo.latest(session, cid, 5):
        lines.append(f"{'⭐' * review.rating} <b>{esc(author.full_name or 'Пользователь')}</b>, "
                     f"{fmt_dt(review.created_at)}\n{esc(truncate(review.text, 400))}\n")
    await render(call, "\n".join(lines), ikb.back_kb(f"co:{cid}:{back}"))
    await call.answer()


# ======================= Отзывы =======================
@router.callback_query(F.data.startswith("rv:"))
async def cb_review_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    cid, back = _parse(call.data)
    company = await company_repo.get(session, cid)
    if company is None:
        await call.answer("Компания не найдена.", show_alert=True)
    elif company.owner_id == db_user.id:
        await call.answer("Нельзя оставлять отзыв о своей компании.", show_alert=True)
    elif await review_repo.get_user_review(session, cid, db_user.id):
        await call.answer("Вы уже оставили отзыв об этой компании.", show_alert=True)
    else:
        await state.update_data(review_back=back)
        await render(call, f"⭐ <b>Отзыв о «{esc(company.name)}»</b>\n\nВыберите оценку:", ikb.rating_kb(cid, back))
        await call.answer()


@router.callback_query(F.data.regexp(r"^rt:\d+:[1-5]$"))
async def cb_review_rating(call: CallbackQuery, state: FSMContext) -> None:
    _, cid, rating = call.data.split(":")
    await state.update_data(review_company=int(cid), review_rating=int(rating))
    await state.set_state(ReviewStates.text)
    await render(call, f"Оценка: {'⭐' * int(rating)}\n\n✍️ Напишите текст отзыва (от 3 до 1000 символов):",
                 ikb.cancel_kb("rvx"))
    await call.answer()


@router.callback_query(F.data == "rvx")
async def cb_review_cancel(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User,
                           is_admin: bool) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("review_company"):
        await show_card(call, session, db_user, is_admin, data["review_company"], data.get("review_back", "cat"),
                        count=False)
    await call.answer("Отменено")


@router.message(ReviewStates.text, F.text, ~F.text.startswith("/"))
async def review_text(message: Message, state: FSMContext, session: AsyncSession, db_user: User, bot: Bot) -> None:
    text = message.text.strip()
    if not 3 <= len(text) <= 1000:
        await toast(message, "Отзыв должен быть от 3 до 1000 символов. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    cid, rating, back = data["review_company"], data["review_rating"], data.get("review_back", "cat")
    await state.clear()
    company = await company_repo.get(session, cid)
    if company is None or await review_repo.get_user_review(session, cid, db_user.id):
        await toast(message, "Не удалось сохранить отзыв.")
        return
    await review_repo.add(session, cid, db_user.id, rating, text)
    await stats.record(session, cid, StatEvent.REVIEW, db_user.id)
    owner = await user_repo.get(session, company.owner_id)
    if owner:
        await NotificationService(bot).send(session, owner.tg_id, t_new_review(company.name, rating, text), "review")
    await render(message, "✅ Спасибо! Ваш отзыв сохранён.", ikb.back_kb(f"co:{cid}:{back}", "⬅ К компании"))


# ======================= Город =======================
async def _ask_city(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CityStates.city)
    await render(event, "📍 <b>Из какого вы города?</b>\n\nВыберите из списка или напишите название — "
                        "покажем компании вашего города.", ikb.city_kb())


async def _save_city(event, state: FSMContext, session: AsyncSession, user: User, is_admin: bool, city: str) -> None:
    await state.clear()
    await user_repo.set_city(session, user, city)
    await _home(event, session, user, is_admin)


@router.callback_query(F.data == "city:change")
async def cb_city_change(call: CallbackQuery, state: FSMContext) -> None:
    await _ask_city(call, state)
    await call.answer()


@router.callback_query(F.data.regexp(r"^city:set:\d+$"))
async def cb_city_set(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    index = int(call.data.split(":")[2])
    if index < len(POPULAR_CITIES):
        await _save_city(call, state, session, db_user, is_admin, POPULAR_CITIES[index])
    await call.answer()


@router.callback_query(F.data == "city:any")
async def cb_city_any(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    await _save_city(call, state, session, db_user, is_admin, "")
    await call.answer("Показываем компании из всех городов")


@router.message(CityStates.city, F.text, ~F.text.startswith("/"))
async def msg_city(message: Message, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    city = " ".join(message.text.split()).title()
    if not 2 <= len(city) <= 60:
        await toast(message, "Введите название города (от 2 до 60 символов).")
        return
    await _save_city(message, state, session, db_user, is_admin, city)
