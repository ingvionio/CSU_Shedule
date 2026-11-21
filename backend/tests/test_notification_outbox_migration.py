"""Миграция очереди: сохранение старых писем, ограничения и внешние ключи."""

from importlib import import_module
from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_upgrade_and_downgrade_preserve_existing_pending_email(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.f3b5c7d9e024_notification_outbox")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            for table in ["messages", "push_subscriptions", "users"]:
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
            connection.execute(text("CREATE TABLE email_outbox (id INTEGER PRIMARY KEY, status VARCHAR(16) NOT NULL)"))
            connection.execute(text("INSERT INTO email_outbox (id, status) VALUES (1, 'pending')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text("SELECT status, next_attempt_at FROM email_outbox")).one() == ("pending", None)
            assert "ix_email_outbox_status_next_attempt_at" in {item["name"] for item in inspect(connection).get_indexes("email_outbox")}
            assert len(inspect(connection).get_check_constraints("push_deliveries")) == 2
            assert {item["options"]["ondelete"] for item in inspect(connection).get_foreign_keys("push_deliveries")} == {"CASCADE", "SET NULL"}
            connection.execute(text(
                "INSERT INTO push_deliveries (message_id, subscription_id, user_id, kind, status, next_attempt_at) "
                "VALUES (1, 1, 1, 'message', 'pending', CURRENT_TIMESTAMP)"
            ))
            assert connection.execute(text("SELECT attempts FROM push_deliveries")).scalar() == 0
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE push_deliveries SET kind='wrong'"))
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE push_deliveries SET status='wrong'"))
            connection.execute(text("DELETE FROM push_subscriptions WHERE id=1"))
            assert connection.execute(text("SELECT subscription_id FROM push_deliveries")).scalar() is None
            connection.execute(text("DELETE FROM messages WHERE id=1"))
            assert connection.execute(text("SELECT COUNT(*) FROM push_deliveries")).scalar() == 0
            migration.downgrade()
            assert "push_deliveries" not in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT id, status FROM email_outbox")).one() == (1, "pending")
            assert "next_attempt_at" not in {item["name"] for item in inspect(connection).get_columns("email_outbox")}
    finally:
        engine.dispose()


def test_postgres_sql(monkeypatch):
    migration = import_module("migrations.versions.f3b5c7d9e024_notification_outbox")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert migration.down_revision == "f3b5c7d9e124"
    assert "next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "ALTER TABLE email_outbox ADD COLUMN next_attempt_at TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE SET NULL" in sql and "ON DELETE CASCADE" in sql
