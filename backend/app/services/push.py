"""Подписки, запись push в очередь и отправка на одно устройство."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, DummyCookieJar, TraceConfig, TraceRequestRedirectParams
from pywebpush import WebPushException, webpush_async

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Message, PushDelivery, PushSubscription

# Подписка больше не существует: браузер отписался или удалил данные сайта.
GONE_STATUSES = {404, 410}


def allowed_endpoint(endpoint: str) -> bool:
    if any(char.isspace() or ord(char) < 32 for char in endpoint) or "\\" in endpoint:
        return False
    try:
        parts = urlsplit(endpoint)
        allowed = get_settings().web_push_hosts.lower().split(",")
        return (
            parts.scheme == "https" and parts.netloc.lower() == parts.hostname
            and parts.hostname in {host.strip() for host in allowed} and bool(parts.path) and not parts.fragment
        )
    except ValueError:
        return False


class PushDestinationError(Exception):
    """Запрещённый адрес или перенаправление push-сервиса."""


async def _reject_redirect(_: ClientSession, __: object, ___: TraceRequestRedirectParams) -> None:
    raise PushDestinationError


def web_configured() -> bool:
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def fcm_configured() -> bool:
    return bool(get_settings().fcm_credentials_file)


def is_configured() -> bool:
    return web_configured() or fcm_configured()


def configured_platforms() -> list[str]:
    return (["web"] if web_configured() else []) + (["fcm"] if fcm_configured() else [])


async def subscribe(
    db: AsyncSession, user_id: int, endpoint: str, p256dh: str | None, auth: str | None,
    user_agent: str | None, platform: str = "web",
) -> PushSubscription:
    """Сохраняет подписку. То же устройство под другим профилем — подписка переходит к нему."""
    subscription = await db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if subscription is None:
        subscription = PushSubscription(endpoint=endpoint)
        db.add(subscription)
    subscription.platform = platform
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


@dataclass(frozen=True)
class SubscriptionData:
    endpoint: str
    p256dh: str | None
    auth: str | None
    platform: str = "web"


@dataclass(frozen=True)
class SendResult:
    status: Literal["sent", "gone", "retry", "failed"]
    error: str | None = None


async def enqueue(db: AsyncSession, message_id: int, user_ids: list[int], kind: str, now: datetime) -> int:
    """Записывает доставки без commit: их сохраняет транзакция сообщения."""
    subscriptions = (await db.scalars(select(PushSubscription).where(
        PushSubscription.user_id.in_(user_ids), PushSubscription.platform.in_(configured_platforms()),
    ))).all()
    db.add_all(
        PushDelivery(
            message_id=message_id, subscription_id=item.id, user_id=item.user_id,
            kind=kind, status="pending", next_attempt_at=now, created_at=now,
        )
        for item in subscriptions
    )
    return len(subscriptions)


async def _send(subscription: SubscriptionData, data: dict) -> None:
    settings = get_settings()
    trace = TraceConfig()
    trace.on_request_redirect.append(_reject_redirect)
    async with ClientSession(cookie_jar=DummyCookieJar(), trace_configs=[trace]) as client:
        await webpush_async(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(data, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=24 * 60 * 60,
            timeout=10,
            aiohttp_session=client,
        )


async def send_one(subscription: SubscriptionData, data: dict) -> SendResult:
    """Возвращает исход отправки; работа с БД остаётся у worker'а."""
    if not allowed_endpoint(subscription.endpoint):
        return SendResult("failed", "Недопустимый адрес push-сервиса")
    try:
        await _send(subscription, data)
    except PushDestinationError:
        return SendResult("failed", "Перенаправление push-сервиса запрещено")
    except WebPushException as error:
        status = error.response.status if error.response is not None else None
        text = f"Ошибка push-сервиса (HTTP {status})" if status is not None else "Ошибка push-сервиса"
        if status in GONE_STATUSES:
            return SendResult("gone", text)
        if status is None or status == 429 or status >= 500:
            return SendResult("retry", text)
        return SendResult("failed", text)
    except (ClientError, OSError) as error:
        return SendResult("retry", f"Ошибка соединения с push-сервисом ({type(error).__name__})")
    except Exception as error:
        return SendResult("failed", f"Ошибка отправки push ({type(error).__name__})")
    return SendResult("sent")
