"""Помощники интерфейса: «один экран» вместо потока сообщений.

Принцип: у каждого чата есть одно рабочее сообщение бота («экран»). Бот редактирует его при нажатии кнопок,
а когда пользователь присылает текст/фото, удаляет это сообщение и превращает экран в следующий шаг.
Ошибки ввода показываются коротким всплывающим сообщением, которое само исчезает.
"""
from __future__ import annotations

import asyncio
import contextlib

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message

from keyboards.reply import MENU_BUTTONS
from states.postgres import state_record, update_session

_screens: dict[int, int] = {}      # chat_id -> id текущего «экрана» (в памяти; после перезапуска создаётся заново)
_kb_sent: set[int] = set()         # чаты, где уже показана нижняя клавиатура
_tasks: set[asyncio.Task] = set()  # ссылки на фоновые задачи удаления


async def _screen_record(event: Message | CallbackQuery, chat_id: int):
    if update_session.get() is not None:
        return await state_record(f"screen:{event.bot.id}:{chat_id}", create=True)
    return None


async def _remember_screen(event: Message | CallbackQuery, chat_id: int, message_id: int) -> None:
    row = await _screen_record(event, chat_id)
    if row is None:
        _screens[chat_id] = message_id
    else:
        row.data = {**row.data, "screen": message_id}


async def keyboard_needed(message: Message) -> bool:
    """Показывает клавиатуру один раз для чата."""
    chat_id = message.chat.id
    row = await _screen_record(message, chat_id)
    if row is not None:
        if row.data.get("keyboard"):
            return False
        row.data = {**row.data, "keyboard": True}
        return True
    if chat_id in _kb_sent:
        return False
    _kb_sent.add(chat_id)
    return True


async def safe_delete(message: Message | None) -> None:
    if isinstance(message, Message):
        with contextlib.suppress(TelegramAPIError):
            await message.delete()


async def _delete_later(message: Message, seconds: float) -> None:
    await asyncio.sleep(seconds)
    await safe_delete(message)


async def _clear_toast(event: Message | CallbackQuery, chat_id: int) -> None:
    row = await _screen_record(event, chat_id)
    if row is not None and row.data.get("toast"):
        with contextlib.suppress(TelegramAPIError):
            await event.bot.delete_message(chat_id, row.data["toast"])
        row.data = {key: value for key, value in row.data.items() if key != "toast"}


async def toast(message: Message, text: str, seconds: float = 6) -> None:
    """Показывает ошибку ввода до следующего действия в вебхуке или до тайм-аута при polling."""
    await safe_delete(message)
    chat_id = message.chat.id
    await _clear_toast(message, chat_id)
    sent = await message.answer(text)
    row = await _screen_record(message, chat_id)
    if row is not None:
        row.data = {**row.data, "toast": sent.message_id}
        return
    task = asyncio.create_task(_delete_later(sent, seconds))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _send(msg: Message, text: str, kb: InlineKeyboardMarkup | None, photo: str | None) -> Message:
    if photo:
        return await msg.answer_photo(photo, caption=text, reply_markup=kb)
    return await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)


async def _render_for_message(event: Message, text: str, kb: InlineKeyboardMarkup | None, photo: str | None) -> None:
    """Ответ на сообщение пользователя: ввод удаляется, экран редактируется (или создаётся заново)."""
    chat = event.chat.id
    # Кнопки нижнего меню и команды — всегда свежий экран внизу чата; ввод в диалогах — правим текущий экран
    fresh = bool(event.text) and (event.text in MENU_BUTTONS or event.text.startswith("/"))
    await safe_delete(event)
    row = await _screen_record(event, chat)
    old = _screens.get(chat) if row is None else row.data.get("screen")
    if old and not photo and not fresh:
        try:
            await event.bot.edit_message_text(text, chat_id=chat, message_id=old, reply_markup=kb,
                                              disable_web_page_preview=True)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
            # сообщение удалено / фото / слишком старое — отправим новое
    if old:
        with contextlib.suppress(TelegramAPIError):
            await event.bot.delete_message(chat, old)
    sent = await _send(event, text, kb, photo)
    await _remember_screen(event, chat, sent.message_id)


async def render(event: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None,
                 photo: str | None = None) -> None:
    """Показывает экран. Для callback редактирует текущее сообщение; для сообщения пользователя — см. выше.

    Telegram не позволяет превратить текст в фото (и наоборот) — тогда старое сообщение заменяется новым.
    """
    if isinstance(event, Message):
        await _clear_toast(event, event.chat.id)
        await _render_for_message(event, text, kb, photo)
        return

    msg = event.message
    if not isinstance(msg, Message):  # устаревшее («недоступное») сообщение
        await _clear_toast(event, event.from_user.id)
        if photo:
            sent = await event.bot.send_photo(event.from_user.id, photo, caption=text, reply_markup=kb)
        else:
            sent = await event.bot.send_message(event.from_user.id, text, reply_markup=kb)
        await _remember_screen(event, event.from_user.id, sent.message_id)
        return

    chat = msg.chat.id
    await _clear_toast(event, chat)
    await _remember_screen(event, chat, msg.message_id)
    current_is_photo = bool(msg.photo)
    try:
        if photo and current_is_photo:
            await msg.edit_media(InputMediaPhoto(media=photo, caption=text), reply_markup=kb)
        elif not photo and not current_is_photo:
            await msg.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:
            await safe_delete(msg)
            sent = await _send(msg, text, kb, photo)
            await _remember_screen(event, chat, sent.message_id)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
