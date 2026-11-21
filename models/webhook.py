from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TelegramState(Base):
    __tablename__ = "telegram_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ProcessedUpdate(Base):
    __tablename__ = "telegram_updates"

    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, index=True)
