"""Web Push о сообщениях (VAPID, pywebpush).

Инбокс — источник истины, push только сообщает о новом. Поэтому ошибки
доставки не пробрасываются: подписки, которые push-сервис объявил
недействительными (404/410), удаляются, остальные ошибки пишутся в лог.
"""

from __future__ import annotations

import json
import logging

from aiohttp import ClientError, ClientSession, DummyCookieJar
from pywebpush import WebPushException, webpush_async
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Message, PushSubscription

logger = logging.getLogger(__name__)

# Подписка больше не существует: браузер отписался или удалил данные сайта.
GONE_STATUSES = {404, 410}


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


async def subscribe(db: AsyncSession, user_id: int, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> PushSubscription:
    """Сохраняет подписку. Тот же браузер под другим профилем — подписка переходит к нему."""
    subscription = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
        db.add(subscription)
    subscription.user_id = user_id
    subscription.p256dh = p256dh
    subscription.auth = auth
    subscription.user_agent = (user_agent or "")[:300] or None
    await db.commit()
    return subscription


async def unsubscribe(db: AsyncSession, user_id: int, subscription_id: int) -> bool:
    result = await db.execute(
        delete(PushSubscription).where(PushSubscription.id == subscription_id, PushSubscription.user_id == user_id)
    )
    await db.commit()
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


async def _send(client: ClientSession, subscription: PushSubscription, data: dict) -> None:
    settings = get_settings()
    await webpush_async(
        subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
        data=json.dumps(data, ensure_ascii=False),
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
        ttl=24 * 60 * 60,
        timeout=10,
        aiohttp_session=client,
    )


async def deliver(db: AsyncSession, message: Message, user_ids: list[int], reminder: bool) -> int:
    """Отправляет push на все устройства студентов. Возвращает число доставленных."""
    subscriptions = (await db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids)))).all()
    data = payload(message, reminder)
    # Соединение с БД понадобится снова только для записи результата.
    await db.commit()
    sent = 0
    async with ClientSession(cookie_jar=DummyCookieJar(), trust_env=True) as client:
        for subscription in subscriptions:
            try:
                await _send(client, subscription, data)
                sent += 1
            except WebPushException as error:
                status = error.response.status if error.response is not None else None
                if status in GONE_STATUSES:
                    await db.delete(subscription)
                else:
                    logger.warning("Push %s не доставлен (%s): %s", subscription.id, status, error)
            except (ClientError, OSError) as error:
                logger.warning("Push %s не доставлен: %s", subscription.id, error)
    await db.commit()
    return sent


async def notify_message(message_id: int, user_ids: list[int], reminder: bool) -> None:
    """Фоновая задача после ответа API: своя сессия, потому что запросная уже закрыта."""
    if not user_ids:
        return
    if not is_configured():
        logger.info("Push не настроен (VAPID_*): сообщение %s, получателей %s", message_id, len(user_ids))
        return
    async with SessionLocal() as db:
        message = await db.get(Message, message_id)
        if message is not None:
            await deliver(db, message, user_ids, reminder)
