"""Способ получения справки и файлы в ответах на обращения.

Revision ID: fc61d2a7e930
Revises: fb43e912ac62
"""

from alembic import op
import sqlalchemy as sa

revision = "fc61d2a7e930"
down_revision = "fb43e912ac62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback_messages", sa.Column("certificate_delivery", sa.String(16), nullable=True))
    op.add_column("feedback_messages", sa.Column("certificate_address", sa.Text(), nullable=True))
    op.create_table(
        "feedback_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reply_id", sa.Integer(), sa.ForeignKey("feedback_replies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_attachments_reply_id", "feedback_attachments", ["reply_id"])
    with op.batch_alter_table("email_outbox") as batch:
        batch.add_column(sa.Column("reply_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_email_outbox_reply", "feedback_replies", ["reply_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("email_outbox") as batch:
        batch.drop_constraint("fk_email_outbox_reply", type_="foreignkey")
        batch.drop_column("reply_id")
    op.drop_index("ix_feedback_attachments_reply_id", table_name="feedback_attachments")
    op.drop_table("feedback_attachments")
    op.drop_column("feedback_messages", "certificate_address")
    op.drop_column("feedback_messages", "certificate_delivery")
