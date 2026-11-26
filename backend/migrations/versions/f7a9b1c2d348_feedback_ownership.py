"""Привязка новых обращений к аккаунту Moodle и индексы ограничений."""

from alembic import op
import sqlalchemy as sa

revision = "f7a9b1c2d348"
down_revision = "f6e8a0b2c357"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("feedback_messages") as batch:
        batch.add_column(sa.Column("author_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_feedback_author", "users", ["author_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_feedback_messages_author_created", ["author_id", "created_at"])
        batch.create_index("ix_feedback_messages_ip_created", ["ip_hash", "created_at"])


def downgrade() -> None:
    with op.batch_alter_table("feedback_messages") as batch:
        batch.drop_index("ix_feedback_messages_ip_created")
        batch.drop_index("ix_feedback_messages_author_created")
        batch.drop_constraint("fk_feedback_author", type_="foreignkey")
        batch.drop_column("author_id")
