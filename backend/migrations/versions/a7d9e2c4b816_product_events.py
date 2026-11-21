"""События для статистики ЛК продукта.

Revision ID: a7d9e2c4b816
Revises: f2a4b6c8d013
"""

from alembic import op
import sqlalchemy as sa

revision: str = "a7d9e2c4b816"
down_revision: str = "f2a4b6c8d013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("device_hash", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=8), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("props", sa.JSON(), nullable=True),
    )
    op.create_index("ix_product_events_name_occurred_at", "product_events", ["name", "occurred_at"])
    op.create_index("ix_product_events_user_id_occurred_at", "product_events", ["user_id", "occurred_at"])
    op.create_index("ix_product_events_device_hash", "product_events", ["device_hash"])


def downgrade() -> None:
    op.drop_index("ix_product_events_device_hash", table_name="product_events")
    op.drop_index("ix_product_events_user_id_occurred_at", table_name="product_events")
    op.drop_index("ix_product_events_name_occurred_at", table_name="product_events")
    op.drop_table("product_events")
