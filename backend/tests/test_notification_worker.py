from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine
"""Очередь уведомлений: транзакции, аренда записей, повторы без сети."""

from datetime import datetime, timedelta, timezone
from threading import get_ident

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Base, EmailOutbox, Message, PushDelivery, PushSubscription, User
from app.schemas.message import MessageIn
from app.services import mailer, messages, push, worker

NOW = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private")
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(full_name="Тестовый студент", device_key_hash="outbox-device")
        session.add(user)
        await session.flush()
        session.add(PushSubscription(user_id=user.id, endpoint="https://push.example.com/1", p256dh="key", auth="auth"))
        await session.commit()
        yield session
    await engine.dispose()


async def create(db, importance="normal"):
    return await messages.create_message(
        db, MessageIn(title="Анкета", body="Заполните", importance=importance, target={"type": "all"}), "admin", NOW
    )


async def delivery(db):
    return (await db.scalars(select(PushDelivery).execution_options(populate_existing=True))).one()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def test_message_and_deliveries_share_commit(db, monkeypatch):
    commit = db.commit
    observed = []

    async def inspect_commit():
        await db.flush()
        observed.append((await db.scalar(select(func.count(Message.id))), await db.scalar(select(func.count(PushDelivery.id)))))
        await commit()

    monkeypatch.setattr(db, "commit", inspect_commit)
    message = await create(db)
    assert observed == [(1, 1)]
    item = await delivery(db)
    assert (item.message_id, item.kind, item.status, item.attempts) == (message.id, "message", "pending", 0)
    assert aware(item.next_attempt_at) == NOW


async def test_failed_commit_rolls_back_message_and_deliveries(db, monkeypatch):
    async def fail():
        await db.flush()
        raise RuntimeError("сбой записи")

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        await create(db)
    await db.rollback()
    assert await db.scalar(select(func.count(Message.id))) == 0
    assert await db.scalar(select(func.count(PushDelivery.id))) == 0


async def test_unknown_group_leaves_no_message_or_delivery(db):
    with pytest.raises(messages.MessageError):
        await messages.create_message(db, MessageIn(title="x", body="y", target={"type": "group", "group_ids": [999]}), "admin")
    assert await db.scalar(select(func.count(Message.id))) == 0
    assert await db.scalar(select(func.count(PushDelivery.id))) == 0


@pytest.mark.parametrize("reason", ["low", "unconfigured"])
async def test_no_push_for_low_or_unconfigured(db, monkeypatch, reason):
    if reason == "unconfigured":
        monkeypatch.setattr(get_settings(), "vapid_private_key", "")
    await create(db, "low" if reason == "low" else "normal")
    assert await db.scalar(select(func.count(PushDelivery.id))) == 0


async def test_push_success_outside_transaction_and_main_thread(db):
    message = await create(db)
    main_thread = get_ident()

    async def send(subscription, data):
        assert get_ident() == main_thread
        assert not db.in_transaction()
        assert data["message_id"] == message.id
        return push.SendResult("sent")

    result = await worker.process_push(db, NOW, sender=send)
    assert result.sent == 1
    item = await delivery(db)
    assert (item.status, item.attempts, aware(item.sent_at)) == ("sent", 1, NOW)


async def test_gone_keeps_statistics_and_deletes_subscription(db):
    await create(db)
    await worker.process_push(db, NOW, sender=AsyncMock(side_effect=lambda *_: push.SendResult("gone", "410")))
    item = await delivery(db)
    assert (item.status, item.subscription_id) == ("gone", None)
    assert await db.scalar(select(func.count(PushSubscription.id))) == 0


async def test_push_retry_schedule_and_limit(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_max_attempts", 5)
    await create(db)
    send = AsyncMock(side_effect=lambda *_: push.SendResult("retry", "500"))
    now = NOW
    for attempt, seconds in enumerate([30, 120, 600, 1800], 1):
        assert (await worker.process_push(db, now, sender=send)).retry == 1
        item = await delivery(db)
        assert item.attempts == attempt and item.status == "pending"
        assert aware(item.next_attempt_at) == now + timedelta(seconds=seconds)
        assert (await worker.process_push(db, now + timedelta(seconds=seconds - 1), sender=send)).processed == 0
        now += timedelta(seconds=seconds)
    assert (await worker.process_push(db, now, sender=send)).failed == 1
    assert ((await delivery(db)).status, (await delivery(db)).attempts) == ("failed", 5)


@pytest.mark.parametrize("reason,status,error", [
    ("deleted", "skipped", None), ("missing_subscription", "skipped", None),
    ("unconfigured", "skipped", "push не настроен"), ("expired", "failed", "истёк срок"),
    ("bad_request", "failed", "400"),
])
async def test_push_terminal_results(db, monkeypatch, reason, status, error):
    message = await create(db)
    now = NOW
    if reason == "deleted":
        message.deleted_at = NOW
    elif reason == "missing_subscription":
        await db.delete((await db.scalars(select(PushSubscription))).one())
    elif reason == "unconfigured":
        monkeypatch.setattr(get_settings(), "vapid_public_key", "")
    elif reason == "expired":
        now += timedelta(hours=24, seconds=1)
    await db.commit()
    await worker.process_push(db, now, sender=AsyncMock(side_effect=lambda *_: push.SendResult("failed", "400")))
    item = await delivery(db)
    assert item.status == status
    if error:
        assert item.last_error == error


@pytest.mark.parametrize("channel", ["push", "email"])
async def test_claim_lease_survives_crash(db, channel):
    if channel == "push":
        await create(db)
        model = PushDelivery
        process = lambda now: worker.process_push(db, now, sender=AsyncMock(side_effect=lambda *_: push.SendResult("sent")))
    else:
        db.add(EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст"))
        await db.commit()
        model = EmailOutbox
        process = lambda now: worker.process_email(db, now, sender=AsyncMock(side_effect=lambda _: mailer.SendResult("sent")))
    claims = await worker.claim(db, model, NOW, 20)
    assert len(claims) == 1
    assert not db.in_transaction()
    assert (await process(NOW + timedelta(minutes=4))).processed == 0
    assert (await process(NOW + timedelta(minutes=5))).sent == 1
    db.expire_all()
    assert (await db.scalars(select(model))).one().attempts == 2


async def test_email_retry_and_failure(db):
    item = EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст")
    db.add(item)
    await db.commit()
    now = NOW
    for seconds in [30, 120, 600, 1800]:
        assert (await worker.process_email(db, now, sender=AsyncMock(side_effect=lambda _: mailer.SendResult("retry", "сбой SMTP")))).retry == 1
        await db.refresh(item)
        assert aware(item.next_attempt_at) == now + timedelta(seconds=seconds)
        assert (await worker.process_email(db, now)).processed == 0
        now += timedelta(seconds=seconds)
    assert (await worker.process_email(db, now, sender=AsyncMock(side_effect=lambda _: mailer.SendResult("retry", "сбой SMTP")))).failed == 1
    await db.refresh(item)
    assert item.status == "failed" and item.attempts == mailer.MAX_ATTEMPTS


@pytest.mark.parametrize("configured", [True, False])
async def test_email_success_or_unconfigured(db, monkeypatch, configured):
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com" if configured else "")
    calls = []

    async def send(item):
        assert not db.in_transaction()
        calls.append(item.to_address)

    monkeypatch.setattr(mailer, "_send", send)
    item = EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст")
    db.add(item)
    await db.commit()
    await worker.process_email(db, NOW)
    await db.refresh(item)
    assert item.status == ("sent" if configured else "skipped")
    assert calls == (["a@example.com"] if configured else [])


@pytest.mark.parametrize("status,expected", [(404, "gone"), (410, "gone"), (429, "retry"), (500, "retry"), (503, "retry"), (400, "failed"), (403, "failed")])
async def test_push_sender_classifies_http_errors(monkeypatch, status, expected):
    from pywebpush import WebPushException

    async def fail(*_):
        raise WebPushException("ошибка", response=type("Response", (), {"status": status})())

    monkeypatch.setattr(push, "_send", fail)
    assert (await push.send_one(push.SubscriptionData("https://push.example.com", "key", "auth"), {})).status == expected


@pytest.mark.parametrize("error", [OSError("сеть"), TimeoutError("таймаут")])
async def test_push_sender_retries_network_errors(monkeypatch, error):
    async def fail(*_):
        raise error

    monkeypatch.setattr(push, "_send", fail)
    assert (await push.send_one(push.SubscriptionData("https://push.example.com", "key", "auth"), {})).status == "retry"


async def test_claim_uses_postgres_skip_locked_and_batch_limit(db, monkeypatch):
    from sqlalchemy.dialects.postgresql import dialect

    monkeypatch.setattr(get_settings(), "push_batch_size", 1)
    message = await create(db)
    user_id = (await db.scalars(select(User.id))).one()
    db.add(PushSubscription(user_id=user_id, endpoint="https://push.example.com/2", p256dh="key", auth="auth"))
    await db.flush()
    await push.enqueue(db, message.id, [user_id], "reminder", NOW)
    await db.commit()
    statements = []

    def capture(context):
        if context.is_select and context.statement._for_update_arg is not None:
            statements.append(str(context.statement.compile(dialect=dialect())))

    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        assert (await worker.process_push(db, NOW, sender=AsyncMock(side_effect=lambda *_: push.SendResult("sent")))).sent == 1
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)
    statements = [sql for sql in statements if "FROM push_deliveries" in sql]
    assert len(statements) == 1
    assert "FOR UPDATE SKIP LOCKED" in statements[0]
    assert "ORDER BY push_deliveries.id" in statements[0] and "LIMIT" in statements[0]
    assert await db.scalar(select(func.count(PushDelivery.id)).where(PushDelivery.status == "pending")) == 2


async def test_old_claim_cannot_overwrite_new_claim(db):
    await create(db)
    old = (await worker.claim(db, PushDelivery, NOW, 1))[0]
    await worker.process_push(db, NOW + worker.LEASE, sender=AsyncMock(side_effect=lambda *_: push.SendResult("sent")))
    await worker._finish(db, PushDelivery, old, "retry", "поздний ответ", NOW, 5)
    assert (await delivery(db)).status == "sent"


async def test_send_emails_uses_same_backoff_and_respects_not_due(db, monkeypatch):
    calls = []
    monkeypatch.setattr(mailer, "_send", AsyncMock(side_effect=calls.append))
    now = datetime.now(timezone.utc)
    db.add_all(EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст", next_attempt_at=due)
               for due in [None, now - timedelta(seconds=1), now + timedelta(hours=1)])
    await db.commit()
    assert await mailer.deliver_pending(db) == 2
    assert len(calls) == 2
    assert await mailer.deliver_pending(db) == 0


async def test_shutdown_finishes_current_pass(monkeypatch):
    handlers = {}
    calls = []

    def register(sig, handler):
        previous = handlers.get(sig)
        handlers[sig] = handler
        return previous

    class Database:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    async def push_batch(*_):
        calls.append("push")
        handlers[worker.signal.SIGTERM](worker.signal.SIGTERM, None)
        return worker.BatchResult(sent=1)

    async def email_batch(*_):
        calls.append("email")
        return worker.BatchResult(sent=1)

    monkeypatch.setattr(worker.signal, "signal", register)
    monkeypatch.setattr(worker, "SessionLocal", Database)
    monkeypatch.setattr(worker, "process_schedule_changes", AsyncMock(side_effect=lambda *_: calls.append("schedule") or 0))
    monkeypatch.setattr(worker, "process_push", push_batch)
    monkeypatch.setattr(worker, "process_email", email_batch)
    await worker.run()
    assert calls == ["schedule", "push", "email"]
    assert all(handler is None for handler in handlers.values())
