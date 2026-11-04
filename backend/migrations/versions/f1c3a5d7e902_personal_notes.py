"""Personal notes, accessible only to their owner."""
from alembic import op
import sqlalchemy as sa

revision = "f1c3a5d7e902"
down_revision = "e8a1b4c7d901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurrence_key", sa.String(64), nullable=False),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "occurrence_key", name="uq_personal_notes_occurrence"),
    )
    op.create_index("ix_personal_notes_user_id", "personal_notes", ["user_id"])


def downgrade():
    op.drop_table("personal_notes")
