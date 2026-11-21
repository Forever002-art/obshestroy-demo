"""Reply-клавиатуры."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_HOME = "🏠 Главная"
BTN_CATALOG = "🔎 Каталог"
BTN_SEARCH = "🔍 Поиск"
BTN_FAVORITES = "⭐ Избранное"
BTN_ABOUT = "ℹ️ О проекте"
BTN_SUPPORT = "📞 Поддержка"
MENU_BUTTONS = {BTN_HOME, BTN_CATALOG, BTN_SEARCH, BTN_FAVORITES, BTN_ABOUT, BTN_SUPPORT}


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_HOME), KeyboardButton(text=BTN_CATALOG)],
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_FAVORITES)],
            [KeyboardButton(text=BTN_ABOUT), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )
