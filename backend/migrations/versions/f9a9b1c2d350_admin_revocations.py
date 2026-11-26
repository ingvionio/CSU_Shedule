"""Серверный отзыв административных JWT."""

from alembic import op
import sqlalchemy as sa

revision = "f9a9b1c2d350"
down_revision = "f8a9b1c2d349"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_feedback_messages_created_id", "feedback_messages", ["created_at", "id"])
    op.create_table(
        "admin_revocations",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("revoked_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_admin_revocations_expires_at", "admin_revocations", ["expires_at"])


def downgrade() -> None:
    op.drop_table("admin_revocations")
    op.drop_index("ix_feedback_messages_created_id", table_name="feedback_messages")
