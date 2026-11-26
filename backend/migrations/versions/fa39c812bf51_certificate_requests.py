"""Добавить папку заказов справок."""

from alembic import op

revision = "fa39c812bf51"
down_revision = "f9a9b1c2d350"
branch_labels = None
depends_on = None

KIND_CONSTRAINT = "ck_feedback_messages_kind"
ORDINARY_KINDS = "kind IN ('dev','methodist','deanery','unknown')"
ALL_KINDS = "kind IN ('dev','methodist','deanery','unknown','certificate')"


def upgrade() -> None:
    with op.batch_alter_table("feedback_messages") as batch:
        batch.drop_constraint(KIND_CONSTRAINT, type_="check")
        batch.create_check_constraint(KIND_CONSTRAINT, ALL_KINDS)


def downgrade() -> None:
    # Старая версия увидит существующие заказы в папке методиста.
    if op.get_context().dialect.name == "postgresql":
        op.execute("LOCK TABLE feedback_messages IN ACCESS EXCLUSIVE MODE")
    op.execute("UPDATE feedback_messages SET kind = 'methodist' WHERE kind = 'certificate'")
    with op.batch_alter_table("feedback_messages") as batch:
        batch.drop_constraint(KIND_CONSTRAINT, type_="check")
        batch.create_check_constraint(KIND_CONSTRAINT, ORDINARY_KINDS)
