"""Хранилище диалогов и обработанных обновлений Telegram."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_state",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("state", sa.String(255)),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    op.create_table(
        "telegram_updates",
        sa.Column("bot_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("update_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_telegram_updates_received_at", "telegram_updates", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_telegram_updates_received_at", table_name="telegram_updates")
    op.drop_table("telegram_updates")
    op.drop_table("telegram_state")
