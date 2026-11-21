"""Сессия и пересдачи: события, группы и история загрузок."""
from alembic import op
import sqlalchemy as sa

revision = "f5d7e9a1b246"
down_revision = "f4c6d8e0a135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("file_name", sa.String(300), nullable=False),
        sa.Column("events_count", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("uploaded_by", sa.String(64)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('session','retake')", name="ck_exam_imports_kind"),
    )
    op.create_index("ix_exam_imports_semester_id", "exam_imports", ["semester_id"])
    op.create_table(
        "exam_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), sa.ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time()),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("teacher", sa.String(200)),
        sa.Column("room", sa.String(200)),
        sa.Column("note", sa.Text()),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("original", sa.JSON(none_as_null=True)),
        sa.Column("event_type", sa.String(24)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("exam_imports.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('session','retake')", name="ck_exam_events_kind"),
        sa.CheckConstraint("source IN ('import','manual')", name="ck_exam_events_source"),
        sa.CheckConstraint("event_type IN ('consultation','exam','credit','graded_credit','other')", name="ck_exam_events_event_type"),
    )
    op.create_index("ix_exam_events_semester_id", "exam_events", ["semester_id"])
    op.create_index("ix_exam_events_semester_kind_date", "exam_events", ["semester_id", "kind", "date"])
    op.create_table(
        "exam_event_groups",
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("exam_events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_exam_event_groups_group_event", "exam_event_groups", ["group_id", "event_id"])


def downgrade() -> None:
    op.drop_table("exam_event_groups")
    op.drop_table("exam_events")
    op.drop_table("exam_imports")
