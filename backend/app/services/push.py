"""Подписки, запись push в очередь и отправка на одно устройство."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from requests.exceptions import RequestException

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Message, PushDelivery, PushSubscription

# Подписка больше не существует: браузер отписался или удалил данные сайта.
GONE_STATUSES = {404, 410}


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def subscribe(db: Session, user_id: int, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> PushSubscription:
    """Сохраняет подписку. Тот же браузер под другим профилем — подписка переходит к нему."""
    subscription = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
        db.add(subscription)
    subscription.user_id = user_id
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.user_agent = (user_agent or "")[:300] or None
    db.commit()
    return subscription


def unsubscribe(db: Session, user_id: int, subscription_id: int) -> bool:
    result = db.execute(
        delete(PushSubscription).where(PushSubscription.id == subscription_id, PushSubscription.user_id == user_id)
    )
    db.commit()
    return result.rowcount > 0


def payload(message: Message, reminder: bool) -> dict:
    title = f"Напоминание: {message.title}" if reminder else message.title
    body = message.body if len(message.body) <= 180 else message.body[:177] + "…"
    return {
        "title": title,
        "body": body,
        "message_id": message.id,
        "importance": message.importance,
        "url": f"/?message={message.id}",
    }


@dataclass(frozen=True)
class SubscriptionData:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class SendResult:
    status: Literal["sent", "gone", "retry", "failed"]
    error: str | None = None


def enqueue(db: Session, message_id: int, user_ids: list[int], kind: str, now: datetime) -> int:
    """Записывает доставки без commit: их сохраняет транзакция сообщения."""
    subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all()
    db.add_all(
        PushDelivery(
            message_id=message_id, subscription_id=item.id, user_id=item.user_id,
            kind=kind, status="pending", next_attempt_at=now, created_at=now,
        )
        for item in subscriptions
    )
    return len(subscriptions)


def _send(subscription: SubscriptionData, data: dict) -> None:
    from pywebpush import webpush

    settings = get_settings()
    webpush(
        subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
        data=json.dumps(data, ensure_ascii=False),
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
        ttl=24 * 60 * 60,
        timeout=10,
    )


def send_one(subscription: SubscriptionData, data: dict) -> SendResult:
    """Возвращает исход отправки; работа с БД остаётся у worker'а."""
    from pywebpush import WebPushException

    try:
        _send(subscription, data)
    except WebPushException as error:
        status = error.response.status_code if error.response is not None else None
        text = str(error)[:500]
        if status in GONE_STATUSES:
            return SendResult("gone", text)
        if status is None or status == 429 or status >= 500:
            return SendResult("retry", text)
        return SendResult("failed", text)
    except (OSError, RequestException) as error:
        return SendResult("retry", str(error)[:500])
    except Exception as error:
        return SendResult("failed", str(error)[:500])
    return SendResult("sent")
