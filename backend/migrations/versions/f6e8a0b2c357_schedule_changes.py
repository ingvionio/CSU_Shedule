"""Очередь уведомлений об изменениях расписания."""
from alembic import op
import sqlalchemy as sa

revision = "f6e8a0b2c357"
down_revision = "f5d7e9a1b246"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("ref_id", sa.Integer()),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("day", sa.Date()),
        sa.Column("text", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source IN ('override','exam','import')", name="ck_schedule_changes_source"),
        sa.CheckConstraint("action IN ('created','changed','removed','uploaded')", name="ck_schedule_changes_action"),
    )
    op.create_index("ix_schedule_changes_group_id", "schedule_changes", ["group_id"])
    op.create_index("ix_schedule_changes_pending", "schedule_changes", ["processed_at", "group_id", "created_at"])


def downgrade() -> None:
    op.drop_table("schedule_changes")
