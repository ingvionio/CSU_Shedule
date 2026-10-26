"""Web Push о сообщениях (VAPID, pywebpush).

Инбокс — источник истины, push только сообщает о новом. Поэтому ошибки
доставки не пробрасываются: подписки, которые push-сервис объявил
недействительными (404/410), удаляются, остальные ошибки пишутся в лог.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Message, PushSubscription

logger = logging.getLogger(__name__)

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


def _send(subscription: PushSubscription, data: dict) -> None:
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


def deliver(db: Session, message: Message, user_ids: list[int], reminder: bool) -> int:
    """Отправляет push на все устройства студентов. Возвращает число доставленных."""
    from pywebpush import WebPushException

    subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all()
    data = payload(message, reminder)
    sent = 0
    for subscription in subscriptions:
        try:
            _send(subscription, data)
            sent += 1
        except WebPushException as error:
            status = error.response.status_code if error.response is not None else None
            if status in GONE_STATUSES:
                db.delete(subscription)
            else:
                logger.warning("Push %s не доставлен (%s): %s", subscription.id, status, error)
        except OSError as error:
            logger.warning("Push %s не доставлен: %s", subscription.id, error)
    db.commit()
    return sent


def notify_message(message_id: int, user_ids: list[int], reminder: bool) -> None:
    """Фоновая задача после ответа API: своя сессия, потому что запросная уже закрыта."""
    if not user_ids:
        return
    if not is_configured():
        logger.info("Push не настроен (VAPID_*): сообщение %s, получателей %s", message_id, len(user_ids))
        return
    with SessionLocal() as db:
        message = db.get(Message, message_id)
        if message is not None:
            deliver(db, message, user_ids, reminder)
