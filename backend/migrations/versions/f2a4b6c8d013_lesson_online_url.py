"""Ссылка на онлайн-занятие.

Revision ID: f2a4b6c8d013
Revises: e8c1b2a3d4f5
"""

from alembic import op
import sqlalchemy as sa

revision: str = "f2a4b6c8d013"
down_revision: str = "e8c1b2a3d4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lessons", sa.Column("online_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("lessons", "online_url")
