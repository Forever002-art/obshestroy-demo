"""Регистрирует вебхук для указанного Telegram-бота."""

import argparse
import asyncio
import os
import re
from urllib.parse import urlsplit

from main import make_bot
from webhook import dispatcher


async def register(url: str, expected_username: str, secret: str) -> None:
    async with make_bot() as bot:
        user = await bot.get_me()
        if not user.username or user.username.casefold() != expected_username:
            raise SystemExit("BOT_TOKEN принадлежит другому боту. Вебхук не изменён.")
        await bot.set_webhook(url, secret_token=secret, max_connections=1,
                              allowed_updates=dispatcher.resolve_used_update_types())
        info = await bot.get_webhook_info()
        if info.url != url:
            raise SystemExit("Telegram не подтвердил адрес вебхука.")
        print(f"Telegram подтвердил вебхук для @{user.username}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Публичный HTTPS-адрес проекта на Vercel")
    parser.add_argument("--bot", required=True, help="Имя тестового бота в Telegram")
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if (origin.scheme != "https" or not origin.hostname or origin.username is not None
            or origin.path not in ("", "/") or origin.query or origin.fragment):
        parser.error("Укажите HTTPS-адрес проекта без пути, параметров и учётных данных.")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        parser.error("Задайте TELEGRAM_WEBHOOK_SECRET из букв A–Z, цифр, дефиса и подчёркивания.")
    try:
        asyncio.run(register(f"https://{origin.netloc}/api/telegram", args.bot.removeprefix("@").casefold(), secret))
    except Exception as exc:
        raise SystemExit(f"Ошибка регистрации вебхука ({type(exc).__name__}).") from None


if __name__ == "__main__":
    main()
