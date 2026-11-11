from importlib import import_module
from io import StringIO

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text


def test_online_url_upgrade_and_downgrade(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.f2a4b6c8d013_lesson_online_url")
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}")
    metadata = MetaData()
    Table("lessons", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO lessons (id) VALUES (1)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            column = next(item for item in inspect(connection).get_columns("lessons") if item["name"] == "online_url")
            assert column["nullable"] and column["type"].length == 500
            assert connection.execute(text("SELECT online_url FROM lessons")).scalar() is None
            migration.downgrade()
            assert [item["name"] for item in inspect(connection).get_columns("lessons")] == ["id"]
            assert connection.execute(text("SELECT id FROM lessons")).scalar() == 1
    finally:
        engine.dispose()


def test_online_url_postgres_sql(monkeypatch):
    migration = import_module("migrations.versions.f2a4b6c8d013_lesson_online_url")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    assert migration.down_revision == "e8c1b2a3d4f5"
    assert "ALTER TABLE lessons ADD COLUMN online_url VARCHAR(500)" in output.getvalue()
    assert "ALTER TABLE lessons DROP COLUMN online_url" in output.getvalue()
