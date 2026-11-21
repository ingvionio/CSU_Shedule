"""Очередь изменений: миграция SQLite и SQL PostgreSQL."""
from importlib import import_module
from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_migration_sqlite(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.f6e8a0b2c357_schedule_changes")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            for table in ("groups", "messages"):
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} VALUES (1)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert {i["name"] for i in inspect(connection).get_indexes("schedule_changes")} == {"ix_schedule_changes_group_id", "ix_schedule_changes_pending"}
            connection.execute(text("INSERT INTO schedule_changes (id, group_id, source, action, text, message_id) VALUES (1, 1, 'override', 'created', 'Отмена', 1)"))
            for sql in ("UPDATE schedule_changes SET source='bad'", "UPDATE schedule_changes SET action='bad'", "UPDATE schedule_changes SET group_id=999"):
                with pytest.raises(IntegrityError):
                    connection.execute(text(sql))
            connection.execute(text("DELETE FROM messages"))
            assert connection.execute(text("SELECT message_id FROM schedule_changes")).scalar() is None
            connection.execute(text("DELETE FROM groups"))
            assert connection.execute(text("SELECT COUNT(*) FROM schedule_changes")).scalar() == 0
            migration.downgrade()
            assert "schedule_changes" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_postgres_sql(monkeypatch):
    migration = import_module("migrations.versions.f6e8a0b2c357_schedule_changes")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert migration.down_revision == "f5d7e9a1b246"
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE CASCADE" in sql and "ON DELETE SET NULL" in sql
    assert "(processed_at, group_id, created_at)" in sql
