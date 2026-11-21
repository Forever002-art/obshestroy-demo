"""Города пользователей и нормализованный город компании

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Простые ADD COLUMN / CREATE INDEX поддерживаются SQLite напрямую (таблицы не пересоздаются)
    op.add_column("users", sa.Column("city", sa.String(120)))
    op.add_column("companies", sa.Column("city_key", sa.String(120), nullable=False, server_default=""))
    op.create_index("ix_companies_city_key", "companies", ["city_key"])
    conn = op.get_bind()
    for company_id, city in conn.execute(sa.text("SELECT id, city FROM companies")).fetchall():
        key = " ".join((city or "").casefold().replace("ё", "е").split())
        conn.execute(sa.text("UPDATE companies SET city_key = :k WHERE id = :i"), {"k": key, "i": company_id})


def downgrade() -> None:
    op.drop_index("ix_companies_city_key", table_name="companies")
    op.drop_column("companies", "city_key")
    op.drop_column("users", "city")
