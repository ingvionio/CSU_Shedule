"""Регрессии слияния: async worker, OAuth и цепочка миграций."""
import asyncio
from datetime import datetime, timezone
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core.config import get_settings
from app.models import PushSubscription, User
from app.services import exam_importer, fcm, push, worker
from tests.test_exams import exam_db  # noqa: F401
from tests.test_notification_worker import NOW, create, db  # noqa: F401


async def test_push_concurrency_and_connection_release(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_concurrency", 2)
    user_id = await db.scalar(select(User.id))
    db.add_all(PushSubscription(user_id=user_id, endpoint=f"https://push.example.com/{n}", p256dh="key", auth="auth")
               for n in range(2, 7))
    await db.commit()
    await create(db)
    entered, release = asyncio.Event(), asyncio.Event()
    running = peak = 0

    async def send(subscription, data):
        nonlocal running, peak
        assert not db.in_transaction()
        running += 1
        peak = max(peak, running)
        if running == 2:
            entered.set()
        try:
            await release.wait()
            return push.SendResult("sent")
        finally:
            running -= 1

    batch = asyncio.create_task(worker.process_push(db, NOW, sender=send))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert db.bind.pool.checkedout() == 0
        async with AsyncSession(db.bind) as reader:
            assert await reader.scalar(select(func.count(User.id))) == 1
        assert not batch.done()
    finally:
        release.set()
        result = await asyncio.wait_for(batch, timeout=3)
    assert peak == 2 and result.sent == 6


async def test_oauth_exchange_uses_async_http_and_45_second_timeout(monkeypatch):
    credentials = Mock(token=None, expiry=None)
    credentials._token_uri = "https://oauth2.googleapis.com/token"
    credentials._make_authorization_grant_assertion.return_value = b"signed-jwt"
    clients = []
    original = httpx.AsyncClient
    loop_thread = get_ident()

    def signed():
        assert get_ident() != loop_thread
        return b"signed-jwt"

    credentials._make_authorization_grant_assertion.side_effect = signed

    async def exchange(request):
        assert request.method == "POST" and str(request.url) == credentials._token_uri
        assert b"assertion=signed-jwt" in request.content
        assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in request.content
        assert request.extensions["timeout"]["read"] == 45
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})

    def client():
        instance = original(transport=httpx.MockTransport(exchange))
        clients.append(instance)
        return instance

    monkeypatch.setattr(fcm.httpx, "AsyncClient", client)
    await fcm._refresh_credentials(credentials)
    assert credentials.token == "fresh"
    assert 3500 < (credentials.expiry - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() <= 3600
    assert clients[0].is_closed


async def test_parallel_oauth_refresh_is_shared_and_stale_401_keeps_new_token(monkeypatch):
    credentials = SimpleNamespace(project_id="project", token=None, valid=False)
    calls = 0

    async def refresh(item):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        item.token, item.valid = "fresh", True

    monkeypatch.setattr(fcm, "_credentials", credentials)
    monkeypatch.setattr(fcm, "_credentials_file", get_settings().fcm_credentials_file)
    monkeypatch.setattr(fcm, "_refresh_credentials", refresh)
    monkeypatch.setattr(fcm, "_lock", asyncio.Lock())
    result = await asyncio.gather(*(fcm._access_token() for _ in range(8)))
    assert result == [("project", "fresh")] * 8 and calls == 1
    await fcm._invalidate_token("old")
    assert credentials.token == "fresh"


@pytest.mark.parametrize("kind,parser", [("session", "parse_session_grid"), ("retake", "parse_workbook")])
async def test_exam_parsers_run_in_worker_thread(exam_db, monkeypatch, kind, parser):
    db, semester, _, _ = exam_db
    loop_thread = get_ident()

    def parse(*args):
        assert get_ident() != loop_thread
        return SimpleNamespace(rows=[], warnings=[], sheets=[])

    monkeypatch.setattr(exam_importer, parser, parse)
    report = await exam_importer.import_workbook(db, b"book", semester, kind, "test.xlsx", "admin")
    assert report.events_count == 0 and not report.applied


def test_cli_worker_runs_async_entrypoint_and_disposes_engine(monkeypatch):
    run, dispose = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker, "run", run)
    monkeypatch.setattr(cli, "engine", SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(cli, "parse_args", lambda: SimpleNamespace(command="worker"))
    cli.main()
    run.assert_awaited_once_with()
    dispose.assert_awaited_once_with()


def test_migration_chain_runs_through_async_environment(tmp_path, monkeypatch):
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    chain = [revision.revision for revision in scripts.walk_revisions()]
    assert scripts.get_heads() == ["f6e8a0b2c357"]
    expected = ["f6e8a0b2c357", "f5d7e9a1b246", "f4c6d8e0a135", "f3b5c7d9e024",
                "f3b5c7d9e124", "a7d9e2c4b816", "f2a4b6c8d013"]
    assert chain[:len(expected)] == expected
    filename = tmp_path / "async-migrations.db"
    monkeypatch.setattr(get_settings(), "database_url", f"sqlite+aiosqlite:///{filename.as_posix()}")
    command.upgrade(config, "f1c3a5d7e902")
    engine = create_engine(f"sqlite:///{filename.as_posix()}")
    try:
        # Прежняя Moodle-миграция ожидает имя UNIQUE из PostgreSQL, SQLite его не создавал.
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            with operations.batch_alter_table(
                "users", recreate="always", naming_convention={"uq": "%(table_name)s_%(column_0_name)s_key"},
            ):
                pass
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == expected[0]
        command.downgrade(config, "f2a4b6c8d013")
        command.upgrade(config, "head")
    finally:
        engine.dispose()


async def test_webpush_uses_async_transport_and_closes_client(monkeypatch):
    clients = []

    async def send(**kwargs):
        assert kwargs["ttl"] == 86400 and kwargs["timeout"] == 10
        assert kwargs["subscription_info"] == {
            "endpoint": "https://push.example.com/1", "keys": {"p256dh": "key", "auth": "auth"},
        }
        assert kwargs["data"] == '{"title": "Пара"}'
        client = kwargs["aiohttp_session"]
        assert not client.closed
        clients.append(client)

    monkeypatch.setattr(push, "webpush_async", AsyncMock(side_effect=send))
    result = await push.send_one(push.SubscriptionData("https://push.example.com/1", "key", "auth"), {"title": "Пара"})
    assert result.status == "sent" and clients[0].closed
