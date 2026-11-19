"""Доставка outbox с короткой арендой записей и повторными попытками."""

from __future__ import annotations

import logging
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Callable, TypeVar

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import EmailOutbox, Message, PushDelivery, PushSubscription
from app.services import fcm, mailer, push

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)
PUSH_TTL = timedelta(hours=24)
EMAIL_BATCH_SIZE = 20
Delivery = TypeVar("Delivery", PushDelivery, EmailOutbox)
PushSender = Callable[[push.SubscriptionData, dict], push.SendResult]
EmailSender = Callable[[mailer.EmailData], mailer.SendResult]


@dataclass(frozen=True)
class Claim:
    id: int
    attempts: int


@dataclass
class BatchResult:
    sent: int = 0
    retry: int = 0
    failed: int = 0
    gone: int = 0
    skipped: int = 0

    @property
    def processed(self) -> int:
        return self.sent + self.retry + self.failed + self.gone + self.skipped


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=(30, 120, 600, 1800)[min(max(attempts - 1, 0), 3)])


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def claim(db: Session, model: type[Delivery], now: datetime, batch: int, ids: list[int] | None = None) -> list[Claim]:
    query = select(model).where(
        model.status == "pending", or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now)
    )
    if ids is not None:
        query = query.where(model.id.in_(ids))
    items = db.scalars(query.order_by(model.id).limit(batch).with_for_update(skip_locked=True)
                       .execution_options(populate_existing=True)).all()
    claimed = []
    for item in items:
        item.attempts += 1
        item.next_attempt_at = now + LEASE
        claimed.append(Claim(item.id, item.attempts))
    db.commit()
    return claimed


def _finish(
    db: Session, model: type[Delivery], item: Claim, status: str, error: str | None,
    now: datetime, max_attempts: int, subscription_id: int | None = None,
) -> str:
    if status == "retry" and item.attempts >= max_attempts:
        status = "failed"
    values = {
        "status": "pending" if status == "retry" else status,
        "last_error": error[:500] if error else None,
        "sent_at": now if status == "sent" else None,
    }
    if status == "retry":
        values["next_attempt_at"] = now + backoff(item.attempts)
    # Просроченный отправитель не должен затереть результат нового владельца аренды.
    result = db.execute(update(model).where(
        model.id == item.id, model.status == "pending", model.attempts == item.attempts,
    ).values(**values).execution_options(synchronize_session=False))
    if result.rowcount and status == "gone" and subscription_id is not None:
        db.execute(update(PushDelivery).where(PushDelivery.subscription_id == subscription_id).values(subscription_id=None))
        db.execute(delete(PushSubscription).where(PushSubscription.id == subscription_id))
    db.commit()
    return status


def _log(channel: str, result: BatchResult) -> None:
    if result.processed:
        logger.info("%s: отправлено %s, повторов %s, ошибок %s, пропущено %s",
                    channel, result.sent, result.retry, result.failed + result.gone, result.skipped)


def process_push(db: Session, now: datetime, sender: PushSender | None = None) -> BatchResult:
    settings = get_settings()
    claimed = claim(db, PushDelivery, now, settings.push_batch_size)
    result = BatchResult()
    if not claimed:
        return result
    rows = db.execute(
        select(PushDelivery, Message, PushSubscription)
        .outerjoin(Message, Message.id == PushDelivery.message_id)
        .outerjoin(PushSubscription, PushSubscription.id == PushDelivery.subscription_id)
        .where(PushDelivery.id.in_([item.id for item in claimed]))
    ).all()
    jobs: dict[int, tuple[push.SubscriptionData, dict]] = {}
    outcomes: dict[int, tuple[str, str | None]] = {}
    subscriptions: dict[int, int | None] = {}
    configured = push.configured_platforms()
    for item, message, subscription in rows:
        subscriptions[item.id] = item.subscription_id
        if message is None or message.deleted_at is not None or subscription is None:
            outcomes[item.id] = ("skipped", None)
        elif subscription.platform not in configured:
            outcomes[item.id] = ("skipped", "push не настроен")
        elif now - _aware(item.created_at) > PUSH_TTL:
            outcomes[item.id] = ("failed", "истёк срок")
        else:
            jobs[item.id] = (
                push.SubscriptionData(subscription.endpoint, subscription.p256dh, subscription.auth, subscription.platform),
                push.payload(message, item.kind == "reminder"),
            )
    # Потокам передаются только снимки данных; транзакция чтения уже закрыта.
    db.commit()
    with ThreadPoolExecutor(max_workers=settings.push_concurrency) as executor:
        futures = {
            item_id: executor.submit(sender or (fcm.send_one if job[0].platform == "fcm" else push.send_one), *job)
            for item_id, job in jobs.items()
        }
        for item in claimed:
            if item.id not in subscriptions:
                continue
            if item.id in futures:
                try:
                    outcome = futures[item.id].result()
                except Exception as error:
                    outcome = push.SendResult("retry", str(error)[:500])
                outcomes[item.id] = (outcome.status, outcome.error)
            status, error = outcomes[item.id]
            status = _finish(db, PushDelivery, item, status, error, now, settings.push_max_attempts, subscriptions[item.id])
            setattr(result, status, getattr(result, status) + 1)
    _log("Push", result)
    return result


def process_email(db: Session, now: datetime, sender: EmailSender | None = None, ids: list[int] | None = None) -> BatchResult:
    claimed = claim(db, EmailOutbox, now, EMAIL_BATCH_SIZE, ids)
    result = BatchResult()
    if not claimed:
        return result
    rows = db.scalars(select(EmailOutbox).where(EmailOutbox.id.in_([item.id for item in claimed]))).all()
    letters = {item.id: mailer.EmailData(item.to_address, item.reply_to, item.subject, item.body) for item in rows}
    db.commit()
    for item in claimed:
        if item.id not in letters:
            continue
        try:
            outcome = (sender or mailer.send_one)(letters[item.id])
        except Exception as error:
            outcome = mailer.SendResult("retry", str(error)[:500])
        status = _finish(db, EmailOutbox, item, outcome.status, outcome.error, now, mailer.MAX_ATTEMPTS)
        setattr(result, status, getattr(result, status) + 1)
    _log("Почта", result)
    return result


def run() -> None:
    stop = Event()

    def shutdown(signum: int, frame: object) -> None:
        stop.set()

    previous = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    now = datetime.now(timezone.utc)
                    pushed = process_push(db, now)
                    emailed = process_email(db, now)
                if not pushed.processed and not emailed.processed:
                    stop.wait(get_settings().worker_poll_seconds)
            except Exception:
                logger.exception("Ошибка прохода worker'а")
                stop.wait(get_settings().worker_poll_seconds)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
