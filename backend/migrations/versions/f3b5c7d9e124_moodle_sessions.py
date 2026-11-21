"""Шифрование Moodle-секретов, отзыв старых сессий и отказ от хранения пароля.

Revision ID: f3b5c7d9e124
Revises: a7d9e2c4b816
"""

from alembic import op
import sqlalchemy as sa

revision = "f3b5c7d9e124"
down_revision = "a7d9e2c4b816"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET moodle_encrypted_password = NULL, moodle_session_cookie = NULL, "
                       "moodle_sesskey = NULL, moodle_session_expires_at = NULL, moodle_auth_error = true"))
    with op.batch_alter_table("users") as batch:
        batch.drop_column("moodle_encrypted_password")
        batch.drop_column("moodle_session_cookie")
        batch.drop_column("moodle_sesskey")
        batch.add_column(sa.Column("moodle_encrypted_cookies", sa.Text(), nullable=True))
        batch.add_column(sa.Column("moodle_encrypted_sesskey", sa.Text(), nullable=True))
        batch.add_column(sa.Column("moodle_session_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("session_last_active_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("moodle_timeout_seconds", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("moodle_refresh_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_users_session_last_active_at", ["session_last_active_at"])
        batch.create_index("ix_users_moodle_refresh_at", ["moodle_refresh_at"])


def downgrade() -> None:
    op.execute(sa.text("UPDATE users SET moodle_session_expires_at = NULL, moodle_auth_error = true"))
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_moodle_refresh_at")
        batch.drop_index("ix_users_session_last_active_at")
        for name in ("moodle_encrypted_cookies", "moodle_encrypted_sesskey", "moodle_session_id",
                     "session_last_active_at", "moodle_timeout_seconds", "moodle_refresh_at"):
            batch.drop_column(name)
        batch.add_column(sa.Column("moodle_encrypted_password", sa.Text(), nullable=True))
        batch.add_column(sa.Column("moodle_session_cookie", sa.Text(), nullable=True))
        batch.add_column(sa.Column("moodle_sesskey", sa.String(64), nullable=True))
