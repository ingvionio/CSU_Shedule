"""group homework and group editors

Revision ID: e8a1b4c7d901
Revises: d2f7b8a91c35
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a1b4c7d901"
down_revision: Union[str, None] = "d2f7b8a91c35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_editors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_editors_group_user"),
    )
    op.create_index("ix_group_editors_group_id", "group_editors", ["group_id"])
    op.create_index("ix_group_editors_user_id", "group_editors", ["user_id"])

    op.create_table(
        "group_homework",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=True),
        sa.Column("lesson_date", sa.Date(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="from_class"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="published"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('from_class','moodle','chat','unknown')", name="ck_group_homework_source"),
        sa.CheckConstraint("status IN ('published','completed','archived')", name="ck_group_homework_status"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_homework_group_id", "group_homework", ["group_id"])
    op.create_index("ix_group_homework_lesson_date", "group_homework", ["lesson_date"])
    op.create_index("ix_group_homework_group_date", "group_homework", ["group_id", "lesson_date", "status"])

    op.create_table(
        "homework_completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("homework_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["homework_id"], ["group_homework.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("homework_id", "user_id", name="uq_homework_completion"),
    )
    op.create_index("ix_homework_completions_homework_id", "homework_completions", ["homework_id"])
    op.create_index("ix_homework_completions_user_id", "homework_completions", ["user_id"])

    op.create_table(
        "homework_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("homework_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["homework_id"], ["group_homework.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_homework_revisions_homework_id", "homework_revisions", ["homework_id"])


def downgrade() -> None:
    op.drop_index("ix_homework_revisions_homework_id", table_name="homework_revisions")
    op.drop_table("homework_revisions")
    op.drop_index("ix_homework_completions_user_id", table_name="homework_completions")
    op.drop_index("ix_homework_completions_homework_id", table_name="homework_completions")
    op.drop_table("homework_completions")
    op.drop_index("ix_group_homework_group_date", table_name="group_homework")
    op.drop_index("ix_group_homework_lesson_date", table_name="group_homework")
    op.drop_index("ix_group_homework_group_id", table_name="group_homework")
    op.drop_table("group_homework")
    op.drop_index("ix_group_editors_user_id", table_name="group_editors")
    op.drop_index("ix_group_editors_group_id", table_name="group_editors")
    op.drop_table("group_editors")
