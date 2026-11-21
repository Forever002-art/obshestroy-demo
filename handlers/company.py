"""Хендлеры компании: регистрация (FSM), личный кабинет, редактирование, подписка и оплата."""
from __future__ import annotations

from dataclasses import asdict

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from config import TARIFFS, settings
from handlers.user import show_card
from keyboards import inline as ikb
from models import Company, CompanyStatus, PaymentStatus, User, utcnow
from repositories import categories as cat_repo
from repositories import companies as company_repo
from repositories import payments as pay_repo
from repositories import reviews as review_repo
from services import company_lookup
from services import company_service as svc
from services import payment_service
from services import statistics_service as stats
from services.company_service import FIELDS, photo_limit
from services.notification_service import NotificationService, t_registered
from states.states import CompanyEditStates, RegistrationStates
from utils import texts
from utils.formatting import esc, fmt_dt, stars, truncate
from utils.logging_setup import company_log, payment_log, registration_log
from utils.ui import render, toast
from utils import validators as v
from utils.validators import is_skip

router = Router(name="company")

# ======================= Регистрация =======================
STEP_ORDER = ["name", "lookup_city", "lookup", "category", "subcategory", "description", "services", "materials", "country", "region",
              "city", "address", "work_hours", "phone", "telegram", "email", "website", "logo", "photos", "confirm"]
TEXT_STEPS = set(FIELDS)
REG_PHOTO_LIMIT = TARIFFS["standard"].max_photos
# Нумеруем только обязательные шаги; подкатегория и поиск в реестре — условные
NUMBERED = [k for k in STEP_ORDER if k not in ("subcategory", "lookup_city", "lookup")]
TOTAL_STEPS = len(NUMBERED)


def _step_number(key: str) -> int:
    return NUMBERED.index(key) + 1


async def _ask(target: Message | CallbackQuery, s: AsyncSession, state: FSMContext, key: str) -> None:
    """Отправляет вопрос очередного шага регистрации (в одном и том же сообщении-экране)."""
    note = (await state.get_data()).get("note")  # например, «данные из реестра подставлены»
    if note:
        await state.update_data(note=None)

    async def out(text: str, kb) -> None:
        await render(target, f"{note}\n\n{text}" if note else text, kb)

    head = f"<b>Шаг {_step_number(key)}/{TOTAL_STEPS}</b>\n" if key in NUMBERED else ""
    if key == "lookup_city":
        await out( "🔎 <b>Автозаполнение</b>\nВ каком городе находится компания? Найдём её в официальном "
                             "реестре и заполним название, адрес и регион автоматически.", ikb.skip_cancel_kb())
    elif key == "lookup":
        hints = (await state.get_data()).get("hints", [])
        await out( "✅ Нашли в реестре. Выберите свою компанию — данные подставятся автоматически:",
                     ikb.lookup_kb(hints))
    elif key == "category":
        cats = await cat_repo.all_categories(s)
        await out( head + "Выберите категорию компании:", ikb.pick_categories_kb(cats, "rc", "reg:cancel"))
    elif key == "subcategory":
        data = await state.get_data()
        subs = await cat_repo.subcategories(s, data["category_id"])
        await out( "Выберите вид материалов:", ikb.pick_subs_kb(subs, "rs", "reg:cancel"))
    elif key in TEXT_STEPS:
        f = FIELDS[key]
        banner = (f"🎁 <b>Первые {settings.trial_days} дн. размещения — бесплатно!</b>\n\n"
                  if key == "name" and settings.trial_days > 0 else "")
        opt = "\n<i>Необязательно — нажмите «Пропустить».</i>" if not f.required else ""
        await out( f"{banner}{head}<b>{f.title}</b>\n{f.hint}{opt}",
                     ikb.skip_cancel_kb() if not f.required else ikb.cancel_kb())
    elif key == "logo":
        await out( head + "<b>Логотип</b>\nОтправьте логотип компании как фото.", ikb.skip_cancel_kb())
    elif key == "photos":
        await out( head + f"<b>Фотографии</b>\nОтправьте до {REG_PHOTO_LIMIT} фото (работы, офис, продукция), "
                     "затем нажмите «Готово».", ikb.photos_done_kb())
    elif key == "confirm":
        data = await state.get_data()
        cat = await cat_repo.get_category(s, data["category_id"])
        sub = await cat_repo.get_subcategory(s, data["subcategory_id"]) if data.get("subcategory_id") else None
        lines = [f"<b>Проверьте заявку</b>\n", f"🏢 <b>{esc(data['name'])}</b>",
                 f"🏷 {esc(cat.title)}" + (f" → {esc(sub.title)}" if sub else "")]
        for k in ("description", "services", "materials", "country", "region", "city", "address", "work_hours",
                  "phone", "telegram", "email", "website"):
            lines.append(f"<b>{FIELDS[k].title}:</b> {esc(truncate(str(data.get(k) or '—'), 200))}")
        lines.append(f"<b>Логотип:</b> {'есть' if data.get('logo') else '—'} · <b>Фото:</b> {len(data.get('photos', []))}")
        await out( "\n".join(lines), ikb.confirm_registration_kb())


async def _advance(target, s: AsyncSession, state: FSMContext, current: str) -> None:
    """Переходит к следующему шагу, пропуская условные и уже заполненные из реестра."""
    data = await state.get_data()
    prefilled = set(data.get("prefilled", []))
    for key in STEP_ORDER[STEP_ORDER.index(current) + 1:]:
        if key == "subcategory" and not data.get("has_subs"):
            continue
        if key == "lookup_city" and not settings.dadata_token:
            continue
        if key == "lookup" and not data.get("hints"):
            continue
        if key in prefilled:
            continue
        await state.set_state(getattr(RegistrationStates, key))
        await _ask(target, s, state, key)
        return


@router.callback_query(F.data == "reg:start")
async def reg_start(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get_by_owner(session, db_user.id)
    if company and company.status != CompanyStatus.REJECTED:
        await call.answer("У вас уже есть зарегистрированная компания.", show_alert=True)
        return
    await state.clear()
    await state.set_state(RegistrationStates.name)
    await _ask(call, session, state, "name")
    await call.answer()


@router.callback_query(F.data == "reg:cancel")
async def reg_cancel(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    await state.clear()
    has_company = await company_repo.get_by_owner(session, db_user.id) is not None
    await render(call, "Действие отменено.", ikb.home_kb(is_admin, has_company, db_user.city))
    await call.answer()


@router.message(RegistrationStates.lookup_city, F.text, ~F.text.startswith("/"))
async def reg_lookup_city(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Город введён -> ищем организацию в реестре по названию + городу."""
    try:
        city = FIELDS["city"].validator(message.text)
    except ValueError as exc:
        await toast(message, f"⚠️ {exc}")
        return
    data = await state.get_data()
    hints = await company_lookup.suggest(data["name"], city)
    prefilled = set(data.get("prefilled", [])) | {"city"}
    await state.update_data(city=city, prefilled=list(prefilled), hints=[asdict(h) for h in hints])
    if not hints:
        await toast(message, "Не нашли такую организацию в реестре — заполним данные вручную.")
    await _advance(message, session, state, "lookup_city")


@router.callback_query(RegistrationStates.lookup, F.data.regexp(r"^lk:(\d+|none)$"))
async def reg_lookup_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    arg = call.data.split(":")[1]
    data = await state.get_data()
    hints = data.get("hints", [])
    await state.update_data(hints=[])
    if arg == "none" or int(arg) >= len(hints):
        await _advance(call, session, state, "lookup")
        await call.answer()
        return
    h = hints[int(arg)]
    updates = {k: h[k] for k in ("name", "country", "region", "city", "address") if h.get(k)}
    for key in ("phone", "email"):
        if h.get(key):
            updates[key] = h[key]
    prefilled = set(data.get("prefilled", []))
    category = next((c for c in await cat_repo.all_categories(session) if c.title == h.get("category_title")), None)
    if category:
        updates.update(category_id=category.id, subcategory_id=None,
                       has_subs=bool(await cat_repo.subcategories(session, category.id)))
        prefilled.add("category")
    prefilled.update(k for k in updates if k in FIELDS)
    await state.update_data(**updates, prefilled=list(prefilled))
    lines = ["✅ <b>Данные из реестра подставлены:</b>", f"🏢 {esc(updates.get('name', '—'))}",
             f"📍 {esc(', '.join(x for x in (updates.get('region'), updates.get('city'), updates.get('address')) if x) or '—')}"]
    if category:
        lines.append(f"🏷 Категория: {esc(category.title)} <i>(определена по ОКВЭД; изменить можно позже в кабинете)</i>")
    lines.append("\nОстальное заполним дальше.")
    await state.update_data(note="\n".join(lines))  # покажем вместе со следующим шагом
    await _advance(call, session, state, "lookup")
    await call.answer()


@router.message(StateFilter(RegistrationStates), F.text, ~F.text.startswith("/"))
async def reg_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    key = (await state.get_state()).split(":")[1]
    if key not in TEXT_STEPS:
        await toast(message, "Пожалуйста, воспользуйтесь кнопками под сообщением выше 👆")
        return
    field = FIELDS[key]
    if not field.required and is_skip(message.text):
        value = None
    else:
        try:
            value = field.validator(message.text)
        except ValueError as exc:
            await toast(message, f"⚠️ {exc}")
            return
    if not await _store_value(message, state, key, value):
        return
    await _advance(message, session, state, key)


async def _store_value(target: Message | CallbackQuery, state: FSMContext, key: str, value: str | None) -> bool:
    data = await state.get_data()
    if key == "materials" and not value and not data.get("services"):
        msg = "⚠️ Укажите хотя бы услуги или материалы — введите материалы текстом."
        if isinstance(target, CallbackQuery):
            await target.answer(msg, show_alert=True)
        else:
            await target.answer(msg)
        return False
    await state.update_data({key: value})
    return True


@router.callback_query(StateFilter(RegistrationStates), F.data == "reg:skip")
async def reg_skip(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    key = (await state.get_state()).split(":")[1]
    if key in TEXT_STEPS and FIELDS[key].required:
        await call.answer("Этот шаг обязателен.", show_alert=True)
        return
    if key in TEXT_STEPS and not await _store_value(call, state, key, None):
        return
    await _advance(call, session, state, key)
    await call.answer()


@router.callback_query(RegistrationStates.category, F.data.regexp(r"^rc:\d+$"))
async def reg_category(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    cat_id = int(call.data.split(":")[1])
    has_subs = bool(await cat_repo.subcategories(session, cat_id))
    await state.update_data(category_id=cat_id, has_subs=has_subs, subcategory_id=None)
    await _advance(call, session, state, "category")
    await call.answer()


@router.callback_query(RegistrationStates.subcategory, F.data.regexp(r"^rs:\d+$"))
async def reg_subcategory(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.update_data(subcategory_id=int(call.data.split(":")[1]))
    await _advance(call, session, state, "subcategory")
    await call.answer()


@router.message(RegistrationStates.logo, F.photo)
async def reg_logo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.update_data(logo=message.photo[-1].file_id)
    await _advance(message, session, state, "logo")


@router.message(RegistrationStates.photos, F.photo)
async def reg_photo(message: Message, state: FSMContext) -> None:
    photos = (await state.get_data()).get("photos", [])
    if len(photos) >= REG_PHOTO_LIMIT:
        await toast(message, f"Достигнут лимит ({REG_PHOTO_LIMIT} фото). Нажмите «Готово». "
                             "Больше фото можно добавить после оформления подписки (Премиум/VIP).")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await render(message, f"📷 Фото добавлено ({len(photos)}/{REG_PHOTO_LIMIT}). Отправьте ещё или нажмите «Готово».",
                 ikb.photos_done_kb())


@router.message(StateFilter(RegistrationStates.logo, RegistrationStates.photos), ~F.photo, ~F.text.startswith("/"))
async def reg_expect_photo(message: Message) -> None:
    await toast(message, "Отправьте изображение как фото (не файлом) или воспользуйтесь кнопками.")


@router.callback_query(RegistrationStates.photos, F.data == "reg:photos_done")
async def reg_photos_done(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await _advance(call, session, state, "photos")
    await call.answer()


@router.callback_query(RegistrationStates.confirm, F.data == "reg:send")
async def reg_send(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    company = await svc.create_company(session, db_user, data)
    notifier = NotificationService(bot)
    await notifier.send(session, db_user.tg_id, t_registered(company.name), "registered")
    await render(call, "✅ Заявка отправлена! Мы уведомим вас о решении.", ikb.back_kb("cab", "🏢 Личный кабинет"))
    from keyboards.inline import _b, _kb  # кнопки быстрой модерации для админов
    await notifier.notify_admins(
        f"🆕 <b>Новая заявка:</b> {esc(company.name)} (#{company.id})\nОт: {esc(db_user.full_name)} "
        f"{'@' + db_user.username if db_user.username else ''}",
        _kb([[_b("✅ Одобрить", f"a:ok:{company.id}"), _b("❌ Отклонить", f"a:no:{company.id}")],
             [_b("👁 Открыть", f"a:c:{company.id}:new")]]))
    registration_log.info("application submitted company=%s", company.id)
    await call.answer()


# ======================= Личный кабинет =======================
async def _my_company(call: CallbackQuery, s: AsyncSession, user: User) -> Company | None:
    company = await company_repo.get_by_owner(s, user.id)
    if company is None:
        await call.answer("Сначала зарегистрируйте компанию.", show_alert=True)
    return company


@router.callback_query(F.data == "cab")
async def cab_home(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    company = await _my_company(call, session, db_user)
    if not company:
        return
    extra = f"\n❗ Причина отклонения: {esc(company.reject_reason or '—')}" if company.status == CompanyStatus.REJECTED else ""
    await render(call, f"🏢 <b>Личный кабинет</b>\n\n<b>{esc(company.name)}</b>\n"
                       f"Статус: {texts.public_status(company)}{extra}\nПодписка до: {fmt_dt(company.subscription_until)}",
                 ikb.cabinet_kb(company))
    await call.answer()


@router.callback_query(F.data == "cab:company")
async def cab_company(call: CallbackQuery, session: AsyncSession, db_user: User, is_admin: bool) -> None:
    company = await _my_company(call, session, db_user)
    if company:
        await show_card(call, session, db_user, is_admin, company.id, "cab", count=False)
        await call.answer()


@router.callback_query(F.data == "cab:edit")
async def cab_edit(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    if await _my_company(call, session, db_user):
        await render(call, "✏ <b>Что изменить?</b>", ikb.fields_kb(ikb.EDIT_KEYS, lambda k: f"ed:{k}", "cab"))
        await call.answer()


@router.callback_query(F.data == "cab:contacts")
async def cab_contacts(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    company = await _my_company(call, session, db_user)
    if company:
        await render(call, texts.contacts_text(company) + "\n\nЧто изменить?",
                     ikb.fields_kb(ikb.CONTACT_KEYS, lambda k: f"ed:{k}", "cab"))
        await call.answer()


@router.callback_query(F.data.startswith("ed:"))
async def cab_edit_field(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    key = call.data.split(":")[1]
    if key == "category":
        cats = await cat_repo.all_categories(session)
        await render(call, "Выберите новую категорию:", ikb.pick_categories_kb(cats, "ec", "cab:edit"))
    elif key in FIELDS:
        f = FIELDS[key]
        await state.set_state(CompanyEditStates.value)
        await state.update_data(field=key)
        note = "\n<i>Отправьте «-», чтобы очистить поле.</i>" if not f.required else ""
        await render(call, f"✏ <b>{f.title}</b>\n{f.hint}{note}\n\nОтправьте новое значение:",
                     ikb.cancel_kb("cab:edit"))
    await call.answer()


@router.message(CompanyEditStates.value, F.text, ~F.text.startswith("/"))
async def cab_edit_value(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get_by_owner(session, db_user.id)
    key = (await state.get_data()).get("field")
    if company is None or key not in FIELDS:
        await state.clear()
        return
    error = await svc.update_field(session, company, key, message.text)
    if error:
        await toast(message, f"⚠️ {error}")
        return
    await state.clear()
    await render(message, "✅ Сохранено.", ikb.back_kb("cab", "🏢 В кабинет"))


@router.callback_query(F.data.regexp(r"^ec:\d+$"))
async def cab_edit_category(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    cat_id = int(call.data.split(":")[1])
    subs = await cat_repo.subcategories(session, cat_id)
    if subs:
        await render(call, "Выберите вид материалов:", ikb.pick_subs_kb(subs, "es", "cab:edit"))
    else:
        await svc.set_category(session, company, cat_id, None)
        await render(call, "✅ Категория изменена.", ikb.back_kb("cab", "🏢 В кабинет"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^es:\d+$"))
async def cab_edit_subcategory(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    sub = await cat_repo.get_subcategory(session, int(call.data.split(":")[1]))
    if company and sub:
        await svc.set_category(session, company, sub.category_id, sub.id)
        await render(call, "✅ Категория изменена.", ikb.back_kb("cab", "🏢 В кабинет"))
        await call.answer()


# ----- Фотографии -----
async def _photos_screen(call: CallbackQuery, company: Company) -> None:
    await render(call, f"📷 <b>Фотографии</b>\n\nЛоготип: {'есть' if company.logo_file_id else '—'}\n"
                       f"Фото: <b>{len(company.photos or [])}/{photo_limit(company)}</b>\n"
                       "Лимит зависит от тарифа (Стандарт — 3, Премиум — 8, VIP — 15).", ikb.photos_menu_kb())


@router.callback_query(F.data == "cab:photos")
async def cab_photos(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    await state.clear()
    company = await _my_company(call, session, db_user)
    if company:
        await _photos_screen(call, company)
        await call.answer()


@router.callback_query(F.data == "ph_add")
async def photos_add(call: CallbackQuery, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    if len(company.photos or []) >= photo_limit(company):
        await call.answer("Достигнут лимит фото по вашему тарифу.", show_alert=True)
        return
    await state.set_state(CompanyEditStates.photos)
    await render(call, "Отправляйте фото по одному или альбомом. Когда закончите — нажмите «Готово».",
                 ikb.photos_done_kb("cab:photos", "cab:photos"))
    await call.answer()


@router.message(CompanyEditStates.photos, F.photo)
async def photos_receive(message: Message, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get_by_owner(session, db_user.id)
    if company is None:
        return
    photos = list(company.photos or [])
    if len(photos) >= photo_limit(company):
        await toast(message, "Лимит фото достигнут. Улучшите тариф, чтобы добавить больше.")
        return
    company.photos = photos + [message.photo[-1].file_id]
    company_log.info("company=%s photo added", company.id)
    await render(message, f"📷 Добавлено ({len(company.photos)}/{photo_limit(company)}). Отправьте ещё или нажмите «Готово».",
                 ikb.photos_done_kb("cab:photos", "cab:photos"))


@router.callback_query(F.data == "ph_logo")
async def logo_change(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CompanyEditStates.logo)
    await render(call, "Отправьте новый логотип как фото.", ikb.cancel_kb("cab:photos"))
    await call.answer()


@router.message(CompanyEditStates.logo, F.photo)
async def logo_receive(message: Message, state: FSMContext, session: AsyncSession, db_user: User) -> None:
    company = await company_repo.get_by_owner(session, db_user.id)
    if company:
        company.logo_file_id = message.photo[-1].file_id
        company_log.info("company=%s logo changed", company.id)
    await state.clear()
    await render(message, "✅ Логотип обновлён.", ikb.back_kb("cab:photos"))


@router.message(StateFilter(CompanyEditStates.photos, CompanyEditStates.logo), ~F.photo, ~F.text.startswith("/"))
async def photos_expect(message: Message) -> None:
    await toast(message, "Отправьте изображение как фото (не файлом).")


@router.callback_query(F.data.in_({"ph_last", "ph_clear"}))
async def photos_delete(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    photos = list(company.photos or [])
    company.photos = photos[:-1] if call.data == "ph_last" else []
    company_log.info("company=%s photos deleted (%s)", company.id, call.data)
    await _photos_screen(call, company)
    await call.answer("Удалено")


# ----- Статистика, отзывы -----
@router.callback_query(F.data == "cab:stats")
async def cab_stats(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if company:
        counts, reviews = await stats.company_counts(session, company.id)
        await render(call, texts.stats_text(company, counts, reviews), ikb.back_kb("cab"))
        await call.answer()


@router.callback_query(F.data == "cab:reviews")
async def cab_reviews(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    avg, cnt = await review_repo.rating(session, company.id)
    lines = [f"⭐ <b>Отзывы</b>\nСредняя оценка: <b>{avg:.1f}</b> {stars(avg)} · отзывов: <b>{cnt}</b>\n"
             if cnt else "⭐ <b>Отзывы</b>\n\nОтзывов пока нет."]
    for r, author in await review_repo.latest(session, company.id, 8):
        lines.append(f"{'⭐' * r.rating} <b>{esc(author.full_name or 'Пользователь')}</b>, {fmt_dt(r.created_at)}\n"
                     f"{esc(truncate(r.text, 300))}\n")
    await render(call, "\n".join(lines), ikb.back_kb("cab"))
    await call.answer()


# ======================= Подписка и оплата =======================
PAYMENT_UNAVAILABLE = "Оплата отключена в демоверсии."


@router.callback_query(F.data == "cab:sub")
async def cab_sub(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    company = await _my_company(call, session, db_user)
    if not company:
        return
    if settings.demo_mode:
        await render(call, texts.subscription_text(company) + "\n\n" + PAYMENT_UNAVAILABLE, ikb.back_kb("cab"))
    elif company.status in (CompanyStatus.PENDING, CompanyStatus.REJECTED):
        await render(call, "💳 Подписку можно оформить после одобрения заявки администратором.", ikb.back_kb("cab"))
    elif company.status == CompanyStatus.BLOCKED:
        await render(call, "⛔ Компания заблокирована. Обратитесь в поддержку.", ikb.back_kb("cab"))
    else:
        await render(call, texts.subscription_text(company) + "\n\n" + texts.tariffs_text() +
                     "\n<i>При смене тарифа срок отсчитывается с момента оплаты.</i>", ikb.tariffs_kb())
    await call.answer()


@router.callback_query(F.data.regexp(r"^sub:(standard|premium|vip)$"))
async def sub_tariff(call: CallbackQuery) -> None:
    if settings.demo_mode:
        await call.answer(PAYMENT_UNAVAILABLE, show_alert=True)
        return
    tariff = TARIFFS[call.data.split(":")[1]]
    await render(call, f"{tariff.mark} <b>{tariff.title}</b> — {tariff.price} ₽/мес\n\nНа какой срок?", ikb.months_kb(tariff.code))
    await call.answer()


@router.callback_query(F.data.regexp(r"^buy:(standard|premium|vip):\d+$"))
async def sub_buy(call: CallbackQuery, session: AsyncSession, db_user: User, bot: Bot) -> None:
    if settings.demo_mode:
        await call.answer(PAYMENT_UNAVAILABLE, show_alert=True)
        return
    company = await _my_company(call, session, db_user)
    if not company or company.status not in (CompanyStatus.APPROVED, CompanyStatus.HIDDEN):
        await call.answer("Подписка недоступна для этой компании.", show_alert=True)
        return
    _, code, months = call.data.split(":")
    tariff, months = TARIFFS[code], int(months)
    provider = "telegram" if settings.payments_enabled else "manual"
    payment = await payment_service.create_payment(session, company, db_user, code, months, provider)
    if provider == "telegram":
        await bot.send_invoice(
            call.from_user.id, title=f"Подписка «{tariff.title}» — {months} мес.",
            description=f"Размещение компании «{company.name}» в каталоге", payload=f"pay:{payment.id}",
            provider_token=settings.payment_provider_token, currency=settings.currency,
            prices=[LabeledPrice(label=f"{tariff.title}, {months} мес.", amount=payment.amount * 100)])
        await call.answer("Счёт отправлен")
        return
    await render(call, f"💳 <b>Оплата: {tariff.mark} {tariff.title}, {months} мес.</b>\nСумма: <b>{payment.amount} ₽</b>\n\n"
                       f"{settings.payment_instructions}\nНомер платежа: <code>#{payment.id}</code>",
                 ikb.manual_pay_kb(payment.id))
    await call.answer()


@router.callback_query(F.data.startswith("paid:"))
async def sub_paid(call: CallbackQuery, session: AsyncSession, db_user: User, bot: Bot) -> None:
    if settings.demo_mode:
        await call.answer(PAYMENT_UNAVAILABLE, show_alert=True)
        return
    payment = await pay_repo.get_payment(session, int(call.data.split(":")[1]))
    if payment is None or payment.user_id != db_user.id or payment.status != PaymentStatus.PENDING:
        await call.answer("Платёж недоступен.", show_alert=True)
        return
    company = await company_repo.get(session, payment.company_id)
    await NotificationService(bot).notify_admins(
        f"💳 <b>Запрос на подтверждение оплаты #{payment.id}</b>\nКомпания: {esc(company.name)}\n"
        f"Тариф: {payment.tariff}, {payment.months} мес.\nСумма: <b>{payment.amount} ₽</b>",
        ikb.admin_payment_kb(payment.id))
    payment_log.info("payment=%s user marked as paid", payment.id)
    await render(call, "⏳ Заявка отправлена администратору. Подписка активируется после проверки оплаты.",
                 ikb.back_kb("cab"))
    await call.answer()


@router.callback_query(F.data.startswith("payx:"))
async def sub_cancel(call: CallbackQuery, session: AsyncSession, db_user: User) -> None:
    payment = await pay_repo.get_payment(session, int(call.data.split(":")[1]))
    if payment and payment.user_id == db_user.id and payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.CANCELLED
    await render(call, "Платёж отменён.", ikb.back_kb("cab:sub"))
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, session: AsyncSession) -> None:
    if settings.demo_mode:
        await query.answer(ok=False, error_message=PAYMENT_UNAVAILABLE)
        return
    payment_id = int(query.invoice_payload.split(":")[1]) if query.invoice_payload.startswith("pay:") else 0
    payment = await pay_repo.get_payment(session, payment_id)
    if payment and payment.status == PaymentStatus.PENDING:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Счёт устарел. Создайте новый платёж.")


@router.message(F.successful_payment)
async def successful_payment(message: Message, session: AsyncSession, bot: Bot) -> None:
    if settings.demo_mode:
        return
    sp = message.successful_payment
    payment = await pay_repo.get_payment(session, int(sp.invoice_payload.split(":")[1]))
    if payment is None:
        payment_log.error("successful_payment for unknown payload %s charge=%s", sp.invoice_payload,
                          sp.telegram_payment_charge_id)
        return
    await payment_service.finalize(session, bot, payment, sp.telegram_payment_charge_id)
    await message.answer("✅ Оплата получена, подписка активирована. Спасибо!")
