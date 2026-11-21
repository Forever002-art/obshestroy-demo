"""Админ-панель: модерация, управление, доход, рассылки, экспорт, бэкапы, настройки."""
from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from config import SUBSCRIPTION_DAYS_PER_MONTH, TARIFFS, settings
from filters import AdminFilter
from keyboards import inline as ikb
from models import CompanyStatus, PaymentStatus, utcnow
from repositories import categories as cat_repo
from repositories import companies as company_repo
from repositories import payments as pay_repo
from repositories import reviews as review_repo
from repositories import system as system_repo
from repositories import users as user_repo
from services import backup_service, export_service, payment_service
from services import company_service as svc
from services import statistics_service as stats
from services.backup_service import BackupError
from services.company_service import FIELDS
from services.notification_service import NotificationService, t_approved, t_rejected
from states.states import AdminStates
from utils.formatting import esc, fmt_dt, money, pages_count, truncate
from utils.logging_setup import admin_log
from utils.texts import company_card
from utils.ui import render, toast

router = Router(name="admin")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())
PAGE = settings.page_size + 3
SETTING_TITLES = {"about_text": "О проекте", "support_text": "Поддержка", "welcome_text": "Приветствие"}


async def _log(s: AsyncSession, admin_id: int, action: str, target: str = "", details: str = "") -> None:
    """Запись в таблицу AdminLogs и в файл admin.log."""
    await system_repo.add_admin_log(s, admin_id, action, target, details)
    admin_log.info("admin=%s action=%s target=%s %s", admin_id, action, target, details)


async def _menu(event: Message | CallbackQuery) -> None:
    await render(event, "🛠 <b>Админ-панель</b>", ikb.admin_menu_kb())


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _menu(message)


@router.callback_query(F.data == "a:menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _menu(call)
    await call.answer()


# ======================= Компании =======================
async def _company_list(call: CallbackQuery, s: AsyncSession, mode: str, page: int) -> None:
    status = CompanyStatus.PENDING if mode == "new" else None
    items, total = await company_repo.admin_page(s, status=status, offset=page * PAGE, limit=PAGE)
    titles = {"all": "🏢 Все компании", "new": "🆕 Новые заявки", "edit": "✏ Редактирование компаний",
              "del": "🗑 Удаление компаний", "block": "⛔ Блокировка компаний", "ext": "⏳ Продление подписок"}
    if not items:
        await render(call, f"<b>{titles[mode]}</b>\n\nСписок пуст.", ikb.back_kb("a:menu"))
        return
    prefix = "a:new" if mode == "new" else f"a:cl:{mode}"
    kb = ikb.admin_list_kb([(ikb.company_label(c), f"a:c:{c.id}:{mode}:{page}") for c in items], prefix, page,
                           pages_count(total, PAGE))
    await render(call, f"<b>{titles[mode]}</b> — всего: {total}", kb)


@router.callback_query(F.data.regexp(r"^a:new:\d+$"))
async def cb_new(call: CallbackQuery, session: AsyncSession) -> None:
    await _company_list(call, session, "new", int(call.data.split(":")[2]))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:cl:\w+:\d+$"))
async def cb_company_list(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, mode, page = call.data.split(":")
    await _company_list(call, session, mode, int(page))
    await call.answer()


async def _company_screen(call: CallbackQuery, s: AsyncSession, company_id: int, mode: str, page: int = 0) -> None:
    company = await company_repo.get(s, company_id)
    if company is None:
        await call.answer("Компания не найдена.", show_alert=True)
        return
    rating = await review_repo.rating(s, company_id)
    back = "a:new:0" if mode == "new" else f"a:cl:{mode}:{page}"
    text = company_card(company, rating, bool(company.logo_file_id))
    await render(call, text, ikb.admin_company_kb(company, mode, back), company.logo_file_id)


@router.callback_query(F.data.regexp(r"^a:c:\d+:\w+(:\d+)?$"))
async def cb_company(call: CallbackQuery, session: AsyncSession) -> None:
    parts = call.data.split(":")
    await _company_screen(call, session, int(parts[2]), parts[3], int(parts[4]) if len(parts) > 4 else 0)
    await call.answer()


async def _notify_owner(bot: Bot, s: AsyncSession, company_id: int, text: str, kind: str) -> None:
    company = await company_repo.get(s, company_id)
    owner = await user_repo.get(s, company.owner_id) if company else None
    if owner:
        await NotificationService(bot).send(s, owner.tg_id, text, kind)


@router.callback_query(F.data.regexp(r"^a:ok:\d+$"))
async def cb_approve(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    company = await company_repo.get(session, int(call.data.split(":")[2]))
    if company is None or company.status != CompanyStatus.PENDING:
        await call.answer("Заявка уже обработана.", show_alert=True)
        return
    await svc.set_status(session, company, CompanyStatus.APPROVED)
    trial = await payment_service.grant_trial(session, company)  # пробная подписка (один раз)
    await _log(session, call.from_user.id, "approve_company", f"company={company.id}", "trial" if trial else "")
    await _notify_owner(bot, session, company.id,
                        t_approved(company.name, company.subscription_until if trial else None), "approved")
    await render(call, f"✅ Компания «{esc(company.name)}» одобрена." + (f"\n🎁 Пробный период до {fmt_dt(company.subscription_until)}." if trial else ""),
                 ikb.back_kb("a:new:0", "⬅ К заявкам"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:no:\d+$"))
async def cb_reject(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.reject_reason)
    await state.update_data(company_id=int(call.data.split(":")[2]))
    await render(call, "Введите причину отклонения (или «-» без причины):", ikb.cancel_kb("a:menu"))
    await call.answer()


@router.message(AdminStates.reject_reason, F.text, ~F.text.startswith("/"))
async def msg_reject(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    company_id = (await state.get_data())["company_id"]
    await state.clear()
    company = await company_repo.get(session, company_id)
    if company is None:
        return
    reason = None if message.text.strip() == "-" else truncate(message.text, 500)
    await svc.set_status(session, company, CompanyStatus.REJECTED, reason)
    await _log(session, message.from_user.id, "reject_company", f"company={company.id}", reason or "")
    await _notify_owner(bot, session, company.id, t_rejected(company.name, reason), "rejected")
    await render(message, f"❌ Заявка «{esc(company.name)}» отклонена.", ikb.back_kb("a:new:0", "⬅ К заявкам"))


@router.callback_query(F.data.regexp(r"^a:(blk|hid):\d+$"))
async def cb_block_hide(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    _, action, cid = call.data.split(":")
    company = await company_repo.get(session, int(cid))
    if company is None:
        return
    if action == "blk":
        new = CompanyStatus.APPROVED if company.status == CompanyStatus.BLOCKED else CompanyStatus.BLOCKED
    else:
        new = CompanyStatus.APPROVED if company.status == CompanyStatus.HIDDEN else CompanyStatus.HIDDEN
    await svc.set_status(session, company, new)
    await _log(session, call.from_user.id, f"company_{new}", f"company={company.id}")
    if new == CompanyStatus.BLOCKED:
        await _notify_owner(bot, session, company.id, f"⛔ Компания «{esc(company.name)}» заблокирована администратором.", "blocked")
    await _company_screen(call, session, company.id, "block")
    await call.answer(CompanyStatus.TITLES[new])


@router.callback_query(F.data.regexp(r"^a:del:\d+$"))
async def cb_delete_ask(call: CallbackQuery) -> None:
    cid = int(call.data.split(":")[2])
    await render(call, "⚠️ Удалить компанию и все её данные (отзывы, избранное, статистика)? Это необратимо.",
                 ikb.admin_confirm_delete_kb(cid))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:delyes:\d+$"))
async def cb_delete(call: CallbackQuery, session: AsyncSession) -> None:
    cid = int(call.data.split(":")[2])
    company = await company_repo.get(session, cid)
    name = company.name if company else str(cid)
    await company_repo.delete_company(session, cid)
    await _log(session, call.from_user.id, "delete_company", f"company={cid}", name)
    await render(call, f"🗑 Компания «{esc(name)}» удалена.", ikb.back_kb("a:cl:del:0", "⬅ К списку"))
    await call.answer()


# ----- Продление подписки -----
@router.callback_query(F.data.regexp(r"^a:ext:\d+$"))
async def cb_extend_menu(call: CallbackQuery) -> None:
    await render(call, "⏳ Выберите тариф и срок бесплатного продления:", ikb.admin_ext_kb(int(call.data.split(":")[2])))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:extdo:\d+:\w+:\d+$"))
async def cb_extend(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    _, _, cid, tariff, months = call.data.split(":")
    company = await company_repo.get(session, int(cid))
    if company is None or tariff not in TARIFFS:
        return
    await payment_service.admin_extend(session, company, tariff, int(months) * SUBSCRIPTION_DAYS_PER_MONTH, call.from_user.id)
    await _log(session, call.from_user.id, "extend_subscription", f"company={cid}", f"{tariff} {months}m")
    from services.notification_service import t_purchased
    await _notify_owner(bot, session, company.id, t_purchased(company.name, tariff, company.subscription_until), "purchase")
    await _company_screen(call, session, company.id, "ext")
    await call.answer("Подписка продлена")


# ----- Подтверждение ручного платежа -----
@router.callback_query(F.data.regexp(r"^a:pay:\d+:(ok|no)$"))
async def cb_payment(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if settings.demo_mode:
        await call.answer("Оплата отключена в демоверсии.", show_alert=True)
        return
    _, _, pid, decision = call.data.split(":")
    payment = await pay_repo.get_payment(session, int(pid))
    if payment is None or payment.status != PaymentStatus.PENDING:
        await call.answer("Платёж уже обработан.", show_alert=True)
        return
    if decision == "ok":
        await payment_service.finalize(session, bot, payment)
    else:
        payment.status = PaymentStatus.CANCELLED
        await _notify_owner(bot, session, payment.company_id, f"❌ Платёж #{payment.id} не подтверждён. Свяжитесь с поддержкой.", "payment_rejected")
    await _log(session, call.from_user.id, f"payment_{decision}", f"payment={pid}", f"{payment.amount}")
    await render(call, f"Платёж #{pid}: {'✅ подтверждён' if decision == 'ok' else '❌ отклонён'}", None)
    await call.answer()


# ----- Редактирование данных компании -----
@router.callback_query(F.data.regexp(r"^a:edit:\d+$"))
async def cb_edit_menu(call: CallbackQuery) -> None:
    cid = call.data.split(":")[2]
    extra = [[ikb._b("🖼 Сменить логотип", f"a:elogo:{cid}"), ikb._b("🧹 Очистить фото", f"a:ephotos:{cid}")]]
    keys = ikb.EDIT_KEYS + ikb.CONTACT_KEYS
    await render(call, "✏ <b>Что изменить?</b>", ikb.fields_kb(keys, lambda k: f"a:ef:{cid}:{k}", f"a:c:{cid}:edit", extra))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:ef:\d+:\w+$"))
async def cb_edit_field(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, cid, key = call.data.split(":")
    if key == "category":
        cats = await cat_repo.all_categories(session)
        await render(call, "Выберите категорию:", ikb.pick_categories_kb(cats, f"a:ecc:{cid}", f"a:edit:{cid}"))
    elif key in FIELDS:
        await state.set_state(AdminStates.edit_value)
        await state.update_data(company_id=int(cid), field=key)
        await render(call, f"✏ <b>{FIELDS[key].title}</b>\nОтправьте новое значение («-» очистит необязательное поле):",
                     ikb.cancel_kb(f"a:edit:{cid}"))
    await call.answer()


@router.message(AdminStates.edit_value, F.text, ~F.text.startswith("/"))
async def msg_edit_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    company = await company_repo.get(session, data["company_id"])
    if company is None:
        await state.clear()
        return
    error = await svc.update_field(session, company, data["field"], message.text)
    if error:
        await toast(message, f"⚠️ {error}")
        return
    await state.clear()
    await _log(session, message.from_user.id, "edit_company", f"company={company.id}", data["field"])
    await render(message, "✅ Сохранено.", ikb.back_kb(f"a:c:{company.id}:edit", "⬅ К компании"))


@router.callback_query(F.data.regexp(r"^a:ecc:\d+:\d+$"))
async def cb_edit_category(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, cid, cat_id = call.data.split(":")
    subs = await cat_repo.subcategories(session, int(cat_id))
    if subs:
        await render(call, "Выберите подкатегорию:", ikb.pick_subs_kb(subs, f"a:ecs:{cid}", f"a:edit:{cid}"))
    else:
        company = await company_repo.get(session, int(cid))
        await svc.set_category(session, company, int(cat_id), None)
        await _log(session, call.from_user.id, "edit_company", f"company={cid}", "category")
        await render(call, "✅ Категория изменена.", ikb.back_kb(f"a:c:{cid}:edit"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:ecs:\d+:\d+$"))
async def cb_edit_subcategory(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, cid, sub_id = call.data.split(":")
    sub = await cat_repo.get_subcategory(session, int(sub_id))
    company = await company_repo.get(session, int(cid))
    if sub and company:
        await svc.set_category(session, company, sub.category_id, sub.id)
        await _log(session, call.from_user.id, "edit_company", f"company={cid}", "category")
        await render(call, "✅ Категория изменена.", ikb.back_kb(f"a:c:{cid}:edit"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:elogo:\d+$"))
async def cb_edit_logo(call: CallbackQuery, state: FSMContext) -> None:
    cid = int(call.data.split(":")[2])
    await state.set_state(AdminStates.edit_logo)
    await state.update_data(company_id=cid)
    await render(call, "Отправьте новый логотип как фото:", ikb.cancel_kb(f"a:edit:{cid}"))
    await call.answer()


@router.message(AdminStates.edit_logo, F.photo)
async def msg_edit_logo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    cid = (await state.get_data())["company_id"]
    company = await company_repo.get(session, cid)
    if company:
        company.logo_file_id = message.photo[-1].file_id
        await _log(session, message.from_user.id, "edit_company", f"company={cid}", "logo")
    await state.clear()
    await render(message, "✅ Логотип обновлён.", ikb.back_kb(f"a:c:{cid}:edit"))


@router.callback_query(F.data.regexp(r"^a:ephotos:\d+$"))
async def cb_clear_photos(call: CallbackQuery, session: AsyncSession) -> None:
    cid = int(call.data.split(":")[2])
    company = await company_repo.get(session, cid)
    if company:
        company.photos = []
        await _log(session, call.from_user.id, "edit_company", f"company={cid}", "photos cleared")
    await call.answer("Фото удалены")


# ======================= Пользователи =======================
@router.callback_query(F.data.regexp(r"^a:ul:\d+$"))
async def cb_users(call: CallbackQuery, session: AsyncSession) -> None:
    page = int(call.data.split(":")[2])
    users = await user_repo.page(session, page * PAGE, PAGE)
    total = await user_repo.count(session)
    items = [(f"{'⛔ ' if u.is_blocked else ''}{u.full_name or u.tg_id} {('@' + u.username) if u.username else ''}",
              f"a:u:{u.id}:{page}") for u in users]
    await render(call, f"👥 <b>Пользователи</b> — всего: {total}", ikb.admin_list_kb(items, "a:ul", page, pages_count(total, PAGE)))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:u:\d+:\d+$"))
async def cb_user(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, uid, page = call.data.split(":")
    user = await user_repo.get(session, int(uid))
    if user is None:
        return
    text = (f"👤 <b>{esc(user.full_name)}</b>\nID: <code>{user.tg_id}</code>\nUsername: {('@' + user.username) if user.username else '—'}\n"
            f"Регистрация: {fmt_dt(user.created_at, True)}\nАктивность: {fmt_dt(user.last_active_at, True)}\n"
            f"Статус: {'⛔ заблокирован' if user.is_blocked else '✅ активен'}")
    await render(call, text, ikb.admin_user_kb(user, int(page)))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:ub:\d+:\d+$"))
async def cb_user_block(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, uid, page = call.data.split(":")
    user = await user_repo.get(session, int(uid))
    if user is None or user.tg_id in settings.admin_ids:
        await call.answer("Нельзя блокировать администратора.", show_alert=True)
        return
    new_value = not user.is_blocked
    await user_repo.set_blocked(session, user.id, new_value)  # синхронизирует объект в сессии
    await _log(session, call.from_user.id, "toggle_user_block", f"user={user.tg_id}", str(new_value))
    await call.answer("⛔ Заблокирован" if new_value else "✅ Разблокирован")
    await cb_user(call, session)


# ======================= Доход, подписки, статистика =======================
@router.callback_query(F.data == "a:inc")
async def cb_income(call: CallbackQuery, session: AsyncSession) -> None:
    now = utcnow()
    rows = {
        "Сегодня": await pay_repo.income_since(session, utcnow().replace(hour=0, minute=0, second=0, microsecond=0)),
        "За 7 дней": await pay_repo.income_since(session, now - timedelta(days=7)),
        "За 30 дней": await pay_repo.income_since(session, now - timedelta(days=30)),
        "Всего": await pay_repo.income_since(session, None),
    }
    lines = ["💰 <b>Доход</b>\n"] + [f"{k}: <b>{money(a)}</b> ({n} плат.)" for k, (a, n) in rows.items()]
    by_tariff = await pay_repo.income_by_tariff(session)
    if by_tariff:
        lines.append("\n<b>По тарифам:</b>")
        lines += [f"{TARIFFS[t].title}: {money(a)} ({n})" for t, a, n in by_tariff if t in TARIFFS]
    await render(call, "\n".join(lines), ikb.back_kb("a:menu"))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:subs:\d+$"))
async def cb_subs(call: CallbackQuery, session: AsyncSession) -> None:
    page = int(call.data.split(":")[2])
    items, total = await company_repo.active_subscriptions_page(session, page * PAGE, PAGE)
    if not items:
        await render(call, "✅ <b>Активные подписки</b>\n\nПока нет.", ikb.back_kb("a:menu"))
    else:
        rows = [(f"{TARIFFS[c.tariff].mark} {c.name} — до {fmt_dt(c.subscription_until)}", f"a:c:{c.id}:ext:0") for c in items]
        await render(call, f"✅ <b>Активные подписки</b> — {total}", ikb.admin_list_kb(rows, "a:subs", page, pages_count(total, PAGE)))
    await call.answer()


@router.callback_query(F.data == "a:stat")
async def cb_stat(call: CallbackQuery, session: AsyncSession) -> None:
    st = await stats.global_stats(session)
    c, ev = st["companies"], st["events"]
    text = (f"📊 <b>Статистика</b>\n\n👥 Пользователей: <b>{st['users']}</b>\n"
            f"🏢 Компаний: <b>{sum(c.values())}</b> (на модерации: {c.get('pending', 0)}, одобрено: {c.get('approved', 0)}, "
            f"отклонено: {c.get('rejected', 0)}, заблокировано: {c.get('blocked', 0)}, скрыто: {c.get('hidden', 0)})\n"
            f"👁 Видно в каталоге: <b>{st['visible']}</b>\n💳 Активных подписок: <b>{st['subscriptions']}</b>\n"
            f"⭐ Отзывов: <b>{st['reviews']}</b>\n❤️ В избранном: <b>{st['favorites']}</b>\n\n"
            f"Показов: {ev.get('impression', 0)} · Открытий карточек: {ev.get('card_open', 0)}\n"
            f"Открытий контактов: {ev.get('contacts_open', 0)} · Переходов в Telegram: {ev.get('tg_click', 0)}")
    await render(call, text, ikb.back_kb("a:menu"))
    await call.answer()


# ======================= Отзывы =======================
async def _reviews_screen(call: CallbackQuery, s: AsyncSession, page: int) -> None:
    rows, total = await review_repo.admin_page(s, page * PAGE, PAGE)
    if not rows:
        await render(call, "⭐ <b>Отзывы</b>\n\nОтзывов нет.", ikb.back_kb("a:menu"))
        return
    lines = [f"⭐ <b>Отзывы</b> — {total}\n"]
    lines += [f"<b>№{r.id}</b> · {esc(name)} · {'⭐' * r.rating}\n{esc(truncate(r.text, 200))}\n" for r, name in rows]
    await render(call, "\n".join(lines), ikb.admin_review_kb([r for r, _ in rows], page, pages_count(total, PAGE)))


@router.callback_query(F.data.regexp(r"^a:rev:\d+$"))
async def cb_reviews(call: CallbackQuery, session: AsyncSession) -> None:
    await _reviews_screen(call, session, int(call.data.split(":")[2]))
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:rd:\d+:\d+$"))
async def cb_review_delete(call: CallbackQuery, session: AsyncSession) -> None:
    _, _, rid, page = call.data.split(":")
    await review_repo.delete_review(session, int(rid))
    await _log(session, call.from_user.id, "delete_review", f"review={rid}")
    await _reviews_screen(call, session, int(page))
    await call.answer("Отзыв удалён")


# ======================= Рассылки =======================
@router.callback_query(F.data.regexp(r"^a:bc:(users|companies)$"))
async def cb_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    audience = call.data.split(":")[2]
    await state.set_state(AdminStates.broadcast_text)
    await state.update_data(audience=audience)
    await render(call, f"📣 Рассылка ({'пользователям' if audience == 'users' else 'компаниям'}).\n\n"
                       "Отправьте текст сообщения (допустима HTML-разметка).", ikb.cancel_kb("a:bcx"))
    await call.answer()


@router.message(AdminStates.broadcast_text, F.text, ~F.text.startswith("/"))
async def msg_broadcast_text(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.html_text)
    await state.set_state(AdminStates.broadcast_confirm)
    await render(message, f"Предпросмотр:\n\n{message.html_text}", ikb.broadcast_confirm_kb())


@router.callback_query(F.data == "a:bcx")
async def cb_broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _menu(call)
    await call.answer("Отменено")


@router.callback_query(AdminStates.broadcast_confirm, F.data == "a:bcgo")
async def cb_broadcast_go(call: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    ids = (await user_repo.broadcast_ids(session) if data["audience"] == "users"
           else await company_repo.owner_tg_ids(session))
    await call.message.edit_text(f"⏳ Рассылка запущена: получателей — {len(ids)}…")
    ok, fail = await NotificationService(bot).broadcast(ids, data["text"])
    await _log(session, call.from_user.id, "broadcast", data["audience"], f"ok={ok} fail={fail}")
    await call.message.edit_text(f"✅ Рассылка завершена. Доставлено: {ok}, ошибок: {fail}.", reply_markup=ikb.back_kb("a:menu"))
    await call.answer()


# ======================= Экспорт, бэкап =======================
@router.callback_query(F.data == "a:xu")
async def cb_export_users(call: CallbackQuery, session: AsyncSession) -> None:
    data = await export_service.users_xlsx(session)
    await call.message.answer_document(BufferedInputFile(data, "users.xlsx"), caption="👥 Пользователи")
    await _log(session, call.from_user.id, "export_users")
    await call.answer()


@router.callback_query(F.data == "a:xc")
async def cb_export_companies(call: CallbackQuery, session: AsyncSession) -> None:
    data = await export_service.companies_xlsx(session)
    await call.message.answer_document(BufferedInputFile(data, "companies.xlsx"), caption="🏢 Компании")
    await _log(session, call.from_user.id, "export_companies")
    await call.answer()


@router.callback_query(F.data == "a:bk")
async def cb_backup(call: CallbackQuery, session: AsyncSession) -> None:
    try:
        path = await backup_service.create_backup()
    except BackupError as exc:
        await call.answer(str(exc), show_alert=True)
        return
    await call.message.answer_document(FSInputFile(path), caption="💾 Резервная копия базы данных")
    await _log(session, call.from_user.id, "backup", path.name)
    await call.answer()


@router.callback_query(F.data == "a:rs")
async def cb_restore_start(call: CallbackQuery, state: FSMContext) -> None:
    if not settings.is_sqlite:
        await call.answer("Для PostgreSQL используйте pg_restore.", show_alert=True)
        return
    await state.set_state(AdminStates.restore_file)
    await render(call, "♻️ <b>Восстановление БД</b>\n\n⚠️ Текущие данные будут заменены. Перед этим автоматически "
                       "создаётся страховочная копия.\nОтправьте файл резервной копии (.db) документом.",
                 ikb.cancel_kb("a:bcx"))
    await call.answer()


@router.message(AdminStates.restore_file, F.document)
async def msg_restore(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    await state.clear()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "restore.db"
        await bot.download(message.document, destination=target)
        try:
            await backup_service.restore_backup(target)
        except BackupError as exc:
            await toast(message, f"❌ {esc(exc)}")
            return
    await render(message, "✅ База данных восстановлена. Рекомендуется перезапустить бота.", ikb.back_kb("a:menu"))


# ======================= Настройки =======================
@router.callback_query(F.data == "a:set")
async def cb_settings(call: CallbackQuery) -> None:
    await render(call, "⚙ <b>Настройки</b>\n\nРедактируемые тексты бота:", ikb.admin_settings_kb())
    await call.answer()


@router.callback_query(F.data.regexp(r"^a:sv:\w+$"))
async def cb_setting_edit(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    key = call.data.split(":")[2]
    if key not in SETTING_TITLES:
        return
    current = await system_repo.get_setting(session, key)
    await state.set_state(AdminStates.setting_value)
    await state.update_data(key=key)
    await render(call, f"Текущий текст «{SETTING_TITLES[key]}»:\n\n{current}\n\n— — —\nОтправьте новый текст (HTML-разметка допустима):",
                 ikb.cancel_kb("a:set"))
    await call.answer()


@router.message(AdminStates.setting_value, F.text, ~F.text.startswith("/"))
async def msg_setting_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    key = (await state.get_data())["key"]
    await state.clear()
    await system_repo.set_setting(session, key, message.html_text)
    await _log(session, message.from_user.id, "edit_setting", key)
    await render(message, "✅ Сохранено.", ikb.back_kb("a:set"))
