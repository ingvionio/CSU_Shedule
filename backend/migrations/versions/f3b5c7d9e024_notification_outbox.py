"""Очередь push и время следующей попытки отправки письма."""

from alembic import op
import sqlalchemy as sa

revision: str = "f3b5c7d9e024"
down_revision: str = "f3b5c7d9e124"  # после Moodle-сессий (ветка Тохи)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("push_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('message','reminder')", name="ck_push_deliveries_kind"),
        sa.CheckConstraint("status IN ('pending','sent','failed','gone','skipped')", name="ck_push_deliveries_status"),
    )
    op.create_index("ix_push_deliveries_message_id", "push_deliveries", ["message_id"])
    op.create_index("ix_push_deliveries_user_id", "push_deliveries", ["user_id"])
    op.create_index("ix_push_deliveries_status_next_attempt_at", "push_deliveries", ["status", "next_attempt_at"])
    op.add_column("email_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_email_outbox_status_next_attempt_at", "email_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_email_outbox_status_next_attempt_at", table_name="email_outbox")
    op.drop_column("email_outbox", "next_attempt_at")
    op.drop_table("push_deliveries")
