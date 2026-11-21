"""Миграция сессии: внешние ключи, ограничения и SQL PostgreSQL."""
from importlib import import_module
from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_exam_migration_sqlite(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.f5d7e9a1b246_exam_events")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            for table in ("semesters", "groups"):
                connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            connection.execute(text("INSERT INTO exam_imports (id, semester_id, kind, file_name, events_count, warnings) VALUES (1, 1, 'session', 'test.xlsx', 1, '[]')"))
            connection.execute(text("INSERT INTO exam_events (id, semester_id, kind, date, subject, source, import_id) VALUES (1, 1, 'session', '2026-10-01', 'История', 'import', 1)"))
            connection.execute(text("INSERT INTO exam_event_groups VALUES (1, 1)"))
            assert connection.execute(text("SELECT cancelled FROM exam_events")).scalar() == 0
            assert connection.execute(text("SELECT created_at, updated_at FROM exam_events")).one()[0] is not None
            assert "ix_exam_events_semester_kind_date" in {item["name"] for item in inspect(connection).get_indexes("exam_events")}
            for statement in ("UPDATE exam_events SET kind='wrong'", "UPDATE exam_events SET source='wrong'",
                              "UPDATE exam_imports SET kind='wrong'", "INSERT INTO exam_event_groups VALUES (1, 1)"):
                with pytest.raises(IntegrityError):
                    connection.execute(text(statement))
            connection.execute(text("DELETE FROM exam_imports"))
            assert connection.execute(text("SELECT import_id FROM exam_events")).scalar() is None
            connection.execute(text("DELETE FROM groups"))
            assert connection.execute(text("SELECT COUNT(*) FROM exam_event_groups")).scalar() == 0
            connection.execute(text("DELETE FROM semesters"))
            assert connection.execute(text("SELECT COUNT(*) FROM exam_events")).scalar() == 0
            migration.downgrade()
            assert not {"exam_events", "exam_imports", "exam_event_groups"} & set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def test_exam_postgres_sql(monkeypatch):
    migration = import_module("migrations.versions.f5d7e9a1b246_exam_events")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert migration.down_revision == "f4c6d8e0a135"
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE SET NULL" in sql and "ON DELETE CASCADE" in sql
    assert "CHECK (kind IN ('session','retake'))" in sql
