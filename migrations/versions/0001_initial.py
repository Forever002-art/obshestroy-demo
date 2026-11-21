"""Начальная схема БД

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "subcategories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint("category_id", "title", name="uq_subcategory_title"),
    )
    op.create_index("ix_subcategories_category_id", "subcategories", ["category_id"])

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), sa.ForeignKey("subcategories.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("short_description", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("services", sa.Text(), nullable=False),
        sa.Column("materials", sa.Text(), nullable=False),
        sa.Column("country", sa.String(80), nullable=False),
        sa.Column("region", sa.String(120), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("work_hours", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("telegram", sa.String(64)),
        sa.Column("email", sa.String(120)),
        sa.Column("website", sa.String(255)),
        sa.Column("logo_file_id", sa.String(256)),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reject_reason", sa.Text()),
        sa.Column("tariff", sa.String(16)),
        sa.Column("subscription_until", sa.DateTime()),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for col in ("category_id", "name", "city", "status", "subscription_until"):
        op.create_index(f"ix_companies_{col}", "companies", [col])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "user_id", name="uq_review_user_company"),
    )
    op.create_index("ix_reviews_company_id", "reviews", ["company_id"])

    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "company_id", name="uq_favorite"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("tariff", sa.String(16), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_charge_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("paid_at", sa.DateTime()),
    )
    op.create_index("ix_payments_company_id", "payments", ["company_id"])
    op.create_index("ix_payments_status", "payments", ["status"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tariff", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("payment_id", sa.Integer()),
    )
    op.create_index("ix_subscriptions_company_id", "subscriptions", ["company_id"])
    op.create_index("ix_subscriptions_is_active", "subscriptions", ["is_active"])

    op.create_table(
        "statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_statistics_company_event", "statistics", ["company_id", "event"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(128), unique=True),
        sa.Column("is_sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_user_tg_id", "notifications", ["user_tg_id"])

    op.create_table(
        "admin_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_admin_logs_admin_tg_id", "admin_logs", ["admin_tg_id"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table in ("settings", "admin_logs", "notifications", "statistics", "subscriptions", "payments",
                  "favorites", "reviews", "companies", "subcategories", "categories", "users"):
        op.drop_table(table)
