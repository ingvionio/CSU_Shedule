"""Очередь уведомлений: транзакции, аренда записей, повторы без сети."""

from datetime import datetime, timedelta, timezone
from threading import get_ident

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Base, EmailOutbox, Message, PushDelivery, PushSubscription, User
from app.schemas.message import MessageIn
from app.services import mailer, messages, push, worker

NOW = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    monkeypatch.setattr(get_settings(), "vapid_public_key", "public")
    monkeypatch.setattr(get_settings(), "vapid_private_key", "private")
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com")
    with Session(engine, expire_on_commit=False) as session:
        user = User(full_name="Тестовый студент", device_key_hash="outbox-device")
        session.add(user)
        session.flush()
        session.add(PushSubscription(user_id=user.id, endpoint="https://push.example.com/1", p256dh="key", auth="auth"))
        session.commit()
        yield session
    engine.dispose()


def create(db, importance="normal"):
    return messages.create_message(
        db, MessageIn(title="Анкета", body="Заполните", importance=importance, target={"type": "all"}), "admin", NOW
    )


def delivery(db):
    db.expire_all()
    return db.scalars(select(PushDelivery)).one()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def test_message_and_deliveries_share_commit(db, monkeypatch):
    commit = db.commit
    observed = []

    def inspect_commit():
        db.flush()
        observed.append((db.scalar(select(func.count(Message.id))), db.scalar(select(func.count(PushDelivery.id)))))
        commit()

    monkeypatch.setattr(db, "commit", inspect_commit)
    message = create(db)
    assert observed == [(1, 1)]
    item = delivery(db)
    assert (item.message_id, item.kind, item.status, item.attempts) == (message.id, "message", "pending", 0)
    assert aware(item.next_attempt_at) == NOW


def test_failed_commit_rolls_back_message_and_deliveries(db, monkeypatch):
    def fail():
        db.flush()
        raise RuntimeError("сбой записи")

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        create(db)
    db.rollback()
    assert db.scalar(select(func.count(Message.id))) == 0
    assert db.scalar(select(func.count(PushDelivery.id))) == 0


def test_unknown_group_leaves_no_message_or_delivery(db):
    with pytest.raises(messages.MessageError):
        messages.create_message(db, MessageIn(title="x", body="y", target={"type": "group", "group_ids": [999]}), "admin")
    assert db.scalar(select(func.count(Message.id))) == 0
    assert db.scalar(select(func.count(PushDelivery.id))) == 0


@pytest.mark.parametrize("reason", ["low", "unconfigured"])
def test_no_push_for_low_or_unconfigured(db, monkeypatch, reason):
    if reason == "unconfigured":
        monkeypatch.setattr(get_settings(), "vapid_private_key", "")
    create(db, "low" if reason == "low" else "normal")
    assert db.scalar(select(func.count(PushDelivery.id))) == 0


def test_push_success_outside_transaction_and_main_thread(db):
    message = create(db)
    main_thread = get_ident()

    def send(subscription, data):
        assert get_ident() != main_thread
        assert not db.in_transaction()
        assert data["message_id"] == message.id
        return push.SendResult("sent")

    result = worker.process_push(db, NOW, sender=send)
    assert result.sent == 1
    item = delivery(db)
    assert (item.status, item.attempts, aware(item.sent_at)) == ("sent", 1, NOW)


def test_gone_keeps_statistics_and_deletes_subscription(db):
    create(db)
    worker.process_push(db, NOW, sender=lambda *_: push.SendResult("gone", "410"))
    item = delivery(db)
    assert (item.status, item.subscription_id) == ("gone", None)
    assert db.scalar(select(func.count(PushSubscription.id))) == 0


def test_push_retry_schedule_and_limit(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_max_attempts", 5)
    create(db)
    send = lambda *_: push.SendResult("retry", "500")
    now = NOW
    for attempt, seconds in enumerate([30, 120, 600, 1800], 1):
        assert worker.process_push(db, now, sender=send).retry == 1
        item = delivery(db)
        assert item.attempts == attempt and item.status == "pending"
        assert aware(item.next_attempt_at) == now + timedelta(seconds=seconds)
        assert worker.process_push(db, now + timedelta(seconds=seconds - 1), sender=send).processed == 0
        now += timedelta(seconds=seconds)
    assert worker.process_push(db, now, sender=send).failed == 1
    assert (delivery(db).status, delivery(db).attempts) == ("failed", 5)


@pytest.mark.parametrize("reason,status,error", [
    ("deleted", "skipped", None), ("missing_subscription", "skipped", None),
    ("unconfigured", "skipped", "push не настроен"), ("expired", "failed", "истёк срок"),
    ("bad_request", "failed", "400"),
])
def test_push_terminal_results(db, monkeypatch, reason, status, error):
    message = create(db)
    now = NOW
    if reason == "deleted":
        message.deleted_at = NOW
    elif reason == "missing_subscription":
        db.delete(db.scalars(select(PushSubscription)).one())
    elif reason == "unconfigured":
        monkeypatch.setattr(get_settings(), "vapid_public_key", "")
    elif reason == "expired":
        now += timedelta(hours=24, seconds=1)
    db.commit()
    worker.process_push(db, now, sender=lambda *_: push.SendResult("failed", "400"))
    item = delivery(db)
    assert item.status == status
    if error:
        assert item.last_error == error


@pytest.mark.parametrize("channel", ["push", "email"])
def test_claim_lease_survives_crash(db, channel):
    if channel == "push":
        create(db)
        model = PushDelivery
        process = lambda now: worker.process_push(db, now, sender=lambda *_: push.SendResult("sent"))
    else:
        db.add(EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст"))
        db.commit()
        model = EmailOutbox
        process = lambda now: worker.process_email(db, now, sender=lambda _: mailer.SendResult("sent"))
    claims = worker.claim(db, model, NOW, 20)
    assert len(claims) == 1
    assert not db.in_transaction()
    assert process(NOW + timedelta(minutes=4)).processed == 0
    assert process(NOW + timedelta(minutes=5)).sent == 1
    db.expire_all()
    assert db.scalars(select(model)).one().attempts == 2


def test_email_retry_and_failure(db):
    item = EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст")
    db.add(item)
    db.commit()
    now = NOW
    for seconds in [30, 120, 600, 1800]:
        assert worker.process_email(db, now, sender=lambda _: mailer.SendResult("retry", "сбой SMTP")).retry == 1
        db.refresh(item)
        assert aware(item.next_attempt_at) == now + timedelta(seconds=seconds)
        assert worker.process_email(db, now).processed == 0
        now += timedelta(seconds=seconds)
    assert worker.process_email(db, now, sender=lambda _: mailer.SendResult("retry", "сбой SMTP")).failed == 1
    db.refresh(item)
    assert item.status == "failed" and item.attempts == mailer.MAX_ATTEMPTS


@pytest.mark.parametrize("configured", [True, False])
def test_email_success_or_unconfigured(db, monkeypatch, configured):
    monkeypatch.setattr(get_settings(), "smtp_user", "bot@example.com" if configured else "")
    calls = []

    def send(item):
        assert not db.in_transaction()
        calls.append(item.to_address)

    monkeypatch.setattr(mailer, "_send", send)
    item = EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст")
    db.add(item)
    db.commit()
    worker.process_email(db, NOW)
    db.refresh(item)
    assert item.status == ("sent" if configured else "skipped")
    assert calls == (["a@example.com"] if configured else [])


@pytest.mark.parametrize("status,expected", [(404, "gone"), (410, "gone"), (429, "retry"), (500, "retry"), (503, "retry"), (400, "failed"), (403, "failed")])
def test_push_sender_classifies_http_errors(monkeypatch, status, expected):
    from pywebpush import WebPushException

    def fail(*_):
        raise WebPushException("ошибка", response=type("Response", (), {"status_code": status})())

    monkeypatch.setattr(push, "_send", fail)
    assert push.send_one(push.SubscriptionData("https://push.example.com", "key", "auth"), {}).status == expected


@pytest.mark.parametrize("error", [OSError("сеть"), TimeoutError("таймаут")])
def test_push_sender_retries_network_errors(monkeypatch, error):
    def fail(*_):
        raise error

    monkeypatch.setattr(push, "_send", fail)
    assert push.send_one(push.SubscriptionData("https://push.example.com", "key", "auth"), {}).status == "retry"


def test_claim_uses_postgres_skip_locked_and_batch_limit(db, monkeypatch):
    from sqlalchemy.dialects.postgresql import dialect

    monkeypatch.setattr(get_settings(), "push_batch_size", 1)
    message = create(db)
    user_id = db.scalars(select(User.id)).one()
    db.add(PushSubscription(user_id=user_id, endpoint="https://push.example.com/2", p256dh="key", auth="auth"))
    db.flush()
    push.enqueue(db, message.id, [user_id], "reminder", NOW)
    db.commit()
    statements = []

    def capture(context):
        if context.is_select and context.statement._for_update_arg is not None:
            statements.append(str(context.statement.compile(dialect=dialect())))

    event.listen(db, "do_orm_execute", capture)
    try:
        assert worker.process_push(db, NOW, sender=lambda *_: push.SendResult("sent")).sent == 1
    finally:
        event.remove(db, "do_orm_execute", capture)
    assert len(statements) == 1
    assert "FOR UPDATE SKIP LOCKED" in statements[0]
    assert "ORDER BY push_deliveries.id" in statements[0] and "LIMIT" in statements[0]
    assert db.scalar(select(func.count(PushDelivery.id)).where(PushDelivery.status == "pending")) == 2


def test_old_claim_cannot_overwrite_new_claim(db):
    create(db)
    old = worker.claim(db, PushDelivery, NOW, 1)[0]
    worker.process_push(db, NOW + worker.LEASE, sender=lambda *_: push.SendResult("sent"))
    worker._finish(db, PushDelivery, old, "retry", "поздний ответ", NOW, 5)
    assert delivery(db).status == "sent"


def test_send_emails_uses_same_backoff_and_respects_not_due(db, monkeypatch):
    calls = []
    monkeypatch.setattr(mailer, "_send", lambda item: calls.append(item))
    now = datetime.now(timezone.utc)
    db.add_all(EmailOutbox(to_address="a@example.com", subject="Тест", body="Текст", next_attempt_at=due)
               for due in [None, now - timedelta(seconds=1), now + timedelta(hours=1)])
    db.commit()
    assert mailer.deliver_pending(db) == 2
    assert len(calls) == 2
    assert mailer.deliver_pending(db) == 0


def test_shutdown_finishes_current_pass(monkeypatch):
    handlers = {}
    calls = []

    def register(sig, handler):
        previous = handlers.get(sig)
        handlers[sig] = handler
        return previous

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def push_batch(*_):
        calls.append("push")
        handlers[worker.signal.SIGTERM](worker.signal.SIGTERM, None)
        return worker.BatchResult(sent=1)

    def email_batch(*_):
        calls.append("email")
        return worker.BatchResult(sent=1)

    monkeypatch.setattr(worker.signal, "signal", register)
    monkeypatch.setattr(worker, "SessionLocal", Database)
    monkeypatch.setattr(worker, "process_schedule_changes", lambda *_: calls.append("schedule") or 0)
    monkeypatch.setattr(worker, "process_push", push_batch)
    monkeypatch.setattr(worker, "process_email", email_batch)
    worker.run()
    assert calls == ["schedule", "push", "email"]
    assert all(handler is None for handler in handlers.values())
