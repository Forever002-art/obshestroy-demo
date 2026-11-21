from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession

from models.webhook import TelegramState

update_session: ContextVar[AsyncSession | None] = ContextVar("update_session", default=None)


async def state_record(key: str, *, create: bool = False) -> TelegramState | None:
    session = update_session.get()
    if session is None:
        raise RuntimeError("PostgreSQL storage requires a webhook transaction")
    row = await session.get(TelegramState, key)
    if row is None and create:
        row = TelegramState(key=key, data={})
        session.add(row)
        await session.flush()
    return row


class PostgresStorage(BaseStorage):
    key_builder = DefaultKeyBuilder(with_bot_id=True, with_business_connection_id=True, with_destiny=True)

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        row = await state_record(self.key_builder.build(key), create=state is not None)
        if row is not None:
            row.state = state.state if isinstance(state, State) else state

    async def get_state(self, key: StorageKey) -> str | None:
        row = await state_record(self.key_builder.build(key))
        return row.state if row is not None else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        row = await state_record(self.key_builder.build(key), create=bool(data))
        if row is not None:
            row.data = deepcopy(dict(data))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await state_record(self.key_builder.build(key))
        return deepcopy(row.data) if row is not None else {}

    async def close(self) -> None:
        pass
