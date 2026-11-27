"""Доставка outbox с короткой арендой записей и повторными попытками."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.rate_limit import prune_quotas
from app.models import EmailOutbox, Group, Message, PushDelivery, PushSubscription, ScheduleChange, User
from app.schemas.message import MessageIn
from app.services import messages, product_events
from app.services import fcm, mailer, push
from app.services import feedback as feedback_service

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=5)
PUSH_TTL = timedelta(hours=24)
EMAIL_BATCH_SIZE = 20
Delivery = TypeVar("Delivery", PushDelivery, EmailOutbox)
PushSender = Callable[[push.SubscriptionData, dict], Awaitable[push.SendResult]]
EmailSender = Callable[[mailer.EmailData], Awaitable[mailer.SendResult]]


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


async def claim(db: AsyncSession, model: type[Delivery], now: datetime, batch: int, ids: list[int] | None = None) -> list[Claim]:
    query = select(model).where(
        model.status == "pending", or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now)
    )
    if ids is not None:
        query = query.where(model.id.in_(ids))
    items = (await db.scalars(query.order_by(model.id).limit(batch).with_for_update(skip_locked=True)
                       .execution_options(populate_existing=True))).all()
    claimed = []
    for item in items:
        item.attempts += 1
        item.next_attempt_at = now + LEASE
        claimed.append(Claim(item.id, item.attempts))
    await db.commit()
    return claimed


async def _finish(
    db: AsyncSession, model: type[Delivery], item: Claim, status: str, error: str | None,
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
    result = await db.execute(update(model).where(
        model.id == item.id, model.status == "pending", model.attempts == item.attempts,
    ).values(**values).execution_options(synchronize_session=False))
    if result.rowcount and model is PushDelivery and status == "sent":
        delivery = (await db.execute(select(
            PushDelivery.user_id, PushDelivery.message_id, PushDelivery.kind, PushDelivery.created_at,
        ).where(PushDelivery.id == item.id))).one()
        # Два устройства одного получателя могут обрабатываться разными worker'ами.
        await db.scalar(select(User.id).where(User.id == delivery.user_id).with_for_update())
        previous = await db.scalar(select(PushDelivery.id).where(
            PushDelivery.id != item.id, PushDelivery.status == "sent",
            PushDelivery.user_id == delivery.user_id, PushDelivery.message_id == delivery.message_id,
            PushDelivery.kind == delivery.kind, PushDelivery.created_at == delivery.created_at,
        ).limit(1))
        if previous is None:
            product_events.add_event(db, product_events.PUSH_SENT, user_id=delivery.user_id,
                                     message_id=delivery.message_id, now=now)
    if result.rowcount and status == "gone" and subscription_id is not None:
        await db.execute(update(PushDelivery).where(PushDelivery.subscription_id == subscription_id).values(subscription_id=None))
        await db.execute(delete(PushSubscription).where(PushSubscription.id == subscription_id))
    await db.commit()
    return status


def _log(channel: str, result: BatchResult) -> None:
    if result.processed:
        logger.info("%s: отправлено %s, повторов %s, ошибок %s, пропущено %s",
                    channel, result.sent, result.retry, result.failed + result.gone, result.skipped)


async def process_push(db: AsyncSession, now: datetime, sender: PushSender | None = None) -> BatchResult:
    settings = get_settings()
    claimed = await claim(db, PushDelivery, now, settings.push_batch_size)
    result = BatchResult()
    if not claimed:
        return result
    rows = (await db.execute(
        select(PushDelivery, Message, PushSubscription)
        .outerjoin(Message, Message.id == PushDelivery.message_id)
        .outerjoin(PushSubscription, PushSubscription.id == PushDelivery.subscription_id)
        .where(PushDelivery.id.in_([item.id for item in claimed]))
    )).all()
    jobs: dict[int, tuple[push.SubscriptionData, dict]] = {}
    outcomes: dict[int, tuple[str, str | None]] = {}
    subscriptions: dict[int, int | None] = {}
    configured = push.configured_platforms()
    for item, message, subscription in rows:
        subscriptions[item.id] = item.subscription_id
        if message is None or message.deleted_at is not None or subscription is None:
            outcomes[item.id] = ("skipped", None)
        elif subscription.user_id != item.user_id:
            outcomes[item.id] = ("skipped", "Владелец push-подписки изменился")
        elif subscription.platform not in configured:
            outcomes[item.id] = ("skipped", "push не настроен")
        elif now - _aware(item.created_at) > PUSH_TTL:
            outcomes[item.id] = ("failed", "истёк срок")
        else:
            jobs[item.id] = (
                push.SubscriptionData(subscription.endpoint, subscription.p256dh, subscription.auth, subscription.platform),
                push.payload(message, item.kind == "reminder"),
            )
    # Сетевым задачам передаём снимки, без открытой транзакции и ORM.
    await db.commit()
    semaphore = asyncio.Semaphore(settings.push_concurrency)

    async def send_job(item_id: int, job: tuple[push.SubscriptionData, dict]) -> None:
        async with semaphore:
            try:
                send = sender or (fcm.send_one if job[0].platform == "fcm" else push.send_one)
                outcome = await send(*job)
            except Exception as error:
                outcome = push.SendResult("retry", f"Ошибка отправки push ({type(error).__name__})")
            outcomes[item_id] = (outcome.status, outcome.error)

    async with asyncio.TaskGroup() as tasks:
        for item_id, job in jobs.items():
            tasks.create_task(send_job(item_id, job))
    for item in claimed:
        if item.id not in subscriptions:
            continue
        status, error = outcomes[item.id]
        status = await _finish(db, PushDelivery, item, status, error, now, settings.push_max_attempts, subscriptions[item.id])
        setattr(result, status, getattr(result, status) + 1)
    _log("Push", result)
    return result


async def process_email(db: AsyncSession, now: datetime, sender: EmailSender | None = None, ids: list[int] | None = None) -> BatchResult:
    claimed = await claim(db, EmailOutbox, now, EMAIL_BATCH_SIZE, ids)
    result = BatchResult()
    if not claimed:
        return result
    rows = (await db.scalars(select(EmailOutbox).where(EmailOutbox.id.in_([item.id for item in claimed])))).all()
    letters = {item.id: mailer.EmailData(item.to_address, item.reply_to, item.subject, item.body) for item in rows}
    reply_ids = {item.id: item.reply_id for item in rows if item.reply_id is not None}
    await db.commit()
    for item in claimed:
        if item.id not in letters:
            continue
        try:
            letter = letters.pop(item.id)
            if item.id in reply_ids:
                # Вложения читаются по одному письму, чтобы не держать в памяти всю пачку.
                files = await feedback_service.reply_files(db, reply_ids[item.id])
                await db.commit()
                letter = replace(letter, attachments=tuple(files))
            outcome = await (sender or mailer.send_one)(letter)
        except Exception as error:
            outcome = mailer.SendResult("retry", f"Ошибка отправки SMTP ({type(error).__name__})")
        status = await _finish(db, EmailOutbox, item, outcome.status, outcome.error, now, mailer.MAX_ATTEMPTS)
        setattr(result, status, getattr(result, status) + 1)
    _log("Почта", result)
    return result


async def process_schedule_changes(db: AsyncSession, now: datetime) -> int:
    cutoff = now - timedelta(seconds=get_settings().schedule_change_delay_seconds)
    candidates = list(await db.scalars(
        select(ScheduleChange.group_id).where(ScheduleChange.processed_at.is_(None))
        .group_by(ScheduleChange.group_id).having(func.max(ScheduleChange.created_at) < cutoff)
        .order_by(ScheduleChange.group_id)
    ))
    sent = 0
    for group_id in candidates:
        # Замок группы не даёт двум worker'ам разделить одну пачку.
        # FOR NO KEY UPDATE: не мешает вставке новых изменений со ссылкой на группу.
        group = await db.scalar(select(Group).where(Group.id == group_id).with_for_update(skip_locked=True, key_share=True))
        if group is None:
            await db.commit()
            continue
        rows = list(await db.scalars(
            select(ScheduleChange).where(ScheduleChange.group_id == group_id, ScheduleChange.processed_at.is_(None))
            .order_by(ScheduleChange.created_at, ScheduleChange.id).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ))
        if not rows or max(_aware(row.created_at) for row in rows) >= cutoff:
            await db.commit()
            continue
        cancelled: set[int] = set()
        created: dict[tuple[str, int], list[int]] = {}
        for index, row in enumerate(rows):
            if row.ref_id is None:
                continue
            key = (row.source, row.ref_id)
            if row.action == "created":
                created.setdefault(key, []).append(index)
            elif row.action == "removed" and created.get(key):
                start = created[key].pop()
                cancelled.update(item.id for item in rows[start:index + 1]
                                 if (item.source, item.ref_id) == key)
        active = sorted((row for row in rows if row.id not in cancelled),
                        key=lambda row: (row.day is None, row.day or now.date(), _aware(row.created_at), row.id))
        message = None
        if active:
            body = "\n".join(row.text for row in active[:10])
            if len(active) > 10:
                body += f"\nи ещё {len(active) - 10}"
            title = active[0].text[:200] if len(active) == 1 and active[0].action == "uploaded" else "Изменение расписания"
            message = await messages.create_message(db, MessageIn(
                title=title, body=body, importance="normal", target={"type": "group", "group_ids": [group_id]},
            ), "system", now, commit=False)
            sent += 1
        for row in rows:
            row.processed_at = now
            row.message_id = message.id if message is not None and row.id not in cancelled else None
        await db.commit()
    return sent


async def run() -> None:
    stop = asyncio.Event()
    last_quota_cleanup = float("-inf")

    def shutdown(signum: int, frame: object) -> None:
        stop.set()

    async def pause() -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=get_settings().worker_poll_seconds)
        except TimeoutError:
            pass

    previous = {sig: signal.signal(sig, shutdown) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        while not stop.is_set():
            try:
                async with SessionLocal() as db:
                    now = datetime.now(timezone.utc)
                    if now.timestamp() - last_quota_cleanup >= 600:
                        await prune_quotas(db)
                        last_quota_cleanup = now.timestamp()
                    changed = await process_schedule_changes(db, now)
                    pushed = await process_push(db, now)
                    emailed = await process_email(db, now)
                if not changed and not pushed.processed and not emailed.processed:
                    await pause()
            except Exception:
                logger.exception("Ошибка прохода worker'а")
                await pause()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
