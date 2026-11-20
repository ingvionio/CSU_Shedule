import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def migration():
    path = Path(__file__).parents[1] / "migrations/versions/f3b5c7d9e124_moodle_sessions.py"
    spec = importlib.util.spec_from_file_location("session_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_and_downgrade_destroy_secrets_but_preserve_profiles(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}")
    metadata = sa.MetaData()
    users = sa.Table("users", metadata,
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("full_name", sa.String(200)),
        sa.Column("moodle_encrypted_password", sa.Text()), sa.Column("moodle_session_cookie", sa.Text()),
        sa.Column("moodle_sesskey", sa.String(64)), sa.Column("moodle_session_expires_at", sa.DateTime(timezone=True)),
        sa.Column("moodle_auth_error", sa.Boolean(), nullable=False, server_default="false"),
    )
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(users.insert().values(id=1, full_name="Студент", moodle_encrypted_password="old-password",
                moodle_session_cookie="plaintext-cookie", moodle_sesskey="plaintext-sesskey"))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration().upgrade()
            row = connection.execute(sa.text("SELECT * FROM users")).mappings().one()
            assert row["full_name"] == "Студент"
            assert row["moodle_session_id"] is None
            assert row["moodle_encrypted_cookies"] is None
            assert row["moodle_encrypted_sesskey"] is None
            assert row["moodle_auth_error"]
            assert "moodle_encrypted_password" not in row
            assert "moodle_session_cookie" not in row
            assert "moodle_sesskey" not in row
            connection.execute(sa.text("UPDATE users SET moodle_session_id = 'new-session', moodle_encrypted_cookies = 'ciphertext'"))
            with Operations.context(context):
                migration().downgrade()
            row = connection.execute(sa.text("SELECT * FROM users")).mappings().one()
            assert row["full_name"] == "Студент"
            assert row["moodle_encrypted_password"] is None
            assert row["moodle_session_cookie"] is None
            assert row["moodle_sesskey"] is None
            assert row["moodle_auth_error"]
    finally:
        engine.dispose()


def test_postgres_migration_sql():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration().upgrade()
        migration().downgrade()
    sql = output.getvalue()
    assert "DROP COLUMN moodle_encrypted_password" in sql
    assert "ADD COLUMN moodle_encrypted_sesskey TEXT" in sql
    assert "CREATE INDEX ix_users_moodle_refresh_at" in sql
