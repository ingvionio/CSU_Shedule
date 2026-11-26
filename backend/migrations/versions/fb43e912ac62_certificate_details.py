"""Добавить цель заказа справки и количество экземпляров."""

from alembic import op
import sqlalchemy as sa

revision = "fb43e912ac62"
down_revision = "fa39c812bf51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # У заказов из предыдущей версии этих данных может не быть.
    op.add_column("feedback_messages", sa.Column("certificate_purpose", sa.Text(), nullable=True))
    op.add_column("feedback_messages", sa.Column("certificate_copies", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback_messages", "certificate_copies")
    op.drop_column("feedback_messages", "certificate_purpose")
