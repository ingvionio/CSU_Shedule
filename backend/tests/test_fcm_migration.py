"""Переход подписок на несколько платформ без потери Web Push."""

from importlib import import_module
from io import StringIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_fcm_migration_preserves_web_and_delivery_history(tmp_path, monkeypatch):
    migration = import_module("migrations.versions.f4c6d8e0a135_fcm_subscriptions")
    engine = create_engine(f"sqlite:///{tmp_path / 'fcm-migration.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE push_subscriptions (id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, p256dh VARCHAR(200) NOT NULL, auth VARCHAR(100) NOT NULL)"))
            connection.execute(text("INSERT INTO push_subscriptions VALUES (1, 'https://push.example.com', 'key', 'auth')"))
            connection.execute(text("CREATE TABLE push_deliveries (id INTEGER PRIMARY KEY, subscription_id INTEGER REFERENCES push_subscriptions(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO push_deliveries VALUES (1, 1)"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text("SELECT platform, p256dh, auth FROM push_subscriptions WHERE id=1")).one() == ("web", "key", "auth")
            columns = {item["name"]: item for item in inspect(connection).get_columns("push_subscriptions")}
            assert not columns["platform"]["nullable"] and columns["platform"]["type"].length == 8
            assert columns["p256dh"]["nullable"] and columns["auth"]["nullable"]
            connection.execute(text("INSERT INTO push_subscriptions (id, endpoint, platform) VALUES (2, 'token-12345678901234567890', 'fcm')"))
            connection.execute(text("INSERT INTO push_deliveries VALUES (2, 2)"))
            with pytest.raises(IntegrityError):
                connection.execute(text("UPDATE push_subscriptions SET platform='hms' WHERE id=2"))
            with pytest.raises(IntegrityError):
                connection.execute(text("INSERT INTO push_subscriptions (endpoint, platform) VALUES ('token-12345678901234567890', 'fcm')"))
            migration.downgrade()
            assert connection.execute(text("SELECT * FROM push_subscriptions")).one() == (1, "https://push.example.com", "key", "auth")
            assert connection.execute(text("SELECT subscription_id FROM push_deliveries ORDER BY id")).all() == [(1,), (None,)]
            columns = {item["name"]: item for item in inspect(connection).get_columns("push_subscriptions")}
            assert "platform" not in columns and not columns["p256dh"]["nullable"] and not columns["auth"]["nullable"]
    finally:
        engine.dispose()


def test_fcm_postgres_sql(monkeypatch):
    migration = import_module("migrations.versions.f4c6d8e0a135_fcm_subscriptions")
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert migration.down_revision == "f3b5c7d9e024"
    assert "DEFAULT 'web' NOT NULL" in sql
    assert "CHECK (platform IN ('web','fcm'))" in sql
    assert "ALTER COLUMN p256dh DROP NOT NULL" in sql
    assert "ALTER COLUMN auth DROP NOT NULL" in sql
