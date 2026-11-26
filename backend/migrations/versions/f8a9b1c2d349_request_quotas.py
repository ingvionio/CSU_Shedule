"""Общие счётчики входов и публичной статистики."""

from alembic import op
import sqlalchemy as sa

revision = "f8a9b1c2d349"
down_revision = "f7a9b1c2d348"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_quotas",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_request_quotas_expires_at", "request_quotas", ["expires_at"])


def downgrade() -> None:
    op.drop_table("request_quotas")
