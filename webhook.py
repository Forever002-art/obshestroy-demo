from datetime import timedelta

from aiogram.dispatcher.middlewares.user_context import UserContextMiddleware
from aiogram.types import Update
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import session_scope
from main import make_bot, make_dispatcher
from models import utcnow
from models.webhook import ProcessedUpdate
from scheduler import check_subscriptions
from states.postgres import PostgresStorage, update_session

if settings.database_url.get_backend_name() != "postgresql" or not settings.demo_mode:
    raise RuntimeError("The demo webhook requires PostgreSQL and DEMO_MODE=true")

dispatcher = make_dispatcher(PostgresStorage())


async def lock(session: AsyncSession, key: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def handle_update(update: Update) -> None:
    context = UserContextMiddleware.resolve_event_context(update)
    chat_id = context.chat_id if context.chat_id is not None else getattr(context.user, "id", None)

    async with make_bot() as bot, session_scope() as session:
        # Telegram может повторно отправить обновление, а Vercel обрабатывает запросы параллельно.
        await lock(session, f"update:{bot.id}:{update.update_id}")
        if await session.get(ProcessedUpdate, (bot.id, update.update_id)) is not None:
            return
        if chat_id is not None:
            await lock(session, f"chat:{bot.id}:{chat_id}")
        token = update_session.set(session)
        try:
            await dispatcher.feed_update(bot, update, webhook_session=session)
        finally:
            update_session.reset(token)
        session.add(ProcessedUpdate(bot_id=bot.id, update_id=update.update_id, received_at=utcnow()))


async def run_daily_jobs() -> None:
    async with make_bot() as bot, session_scope() as session:
        await lock(session, f"daily:{bot.id}")
        await check_subscriptions(bot)
        await session.execute(delete(ProcessedUpdate).where(ProcessedUpdate.received_at < utcnow() - timedelta(days=2)))
