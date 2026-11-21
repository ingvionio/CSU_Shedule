"""Асинхронная отправка писем из outbox через SMTP."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal

from aiosmtplib import send
from aiosmtplib.errors import SMTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import EmailOutbox

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class EmailData:
    to_address: str
    reply_to: str | None
    subject: str
    body: str


@dataclass(frozen=True)
class SendResult:
    status: Literal["sent", "retry", "skipped"]
    error: str | None = None


async def _send(item: EmailData) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_user))
    message["To"] = item.to_address
    if item.reply_to:
        message["Reply-To"] = item.reply_to
    message["Subject"] = item.subject
    message.set_content(item.body)
    await send(
        message, hostname=settings.smtp_host, port=settings.smtp_port,
        username=settings.smtp_user, password=settings.smtp_password, use_tls=True, timeout=20,
    )


async def send_one(item: EmailData) -> SendResult:
    """Отправляет одно письмо без обращения к БД."""
    if not get_settings().smtp_user:
        logger.info("Почта не настроена, письмо не отправлено: %s → %s\n%s", item.subject, item.to_address, item.body)
        return SendResult("skipped", "SMTP не настроен")
    try:
        await _send(item)
    except (OSError, SMTPException) as error:
        return SendResult("retry", str(error)[:500])
    return SendResult("sent")


async def deliver(db: AsyncSession, items: list[EmailOutbox]) -> None:
    """Ручная отправка через тот же захват и обработчик, что у worker'а."""
    from app.services.worker import process_email

    ids = [item.id for item in items]
    now = datetime.now(timezone.utc)
    while (await process_email(db, now, ids=ids)).processed:
        pass
    for item in items:
        await db.refresh(item)


async def deliver_pending(db: AsyncSession) -> int:
    """Досылает письма, которым подошёл срок; возвращает число попыток."""
    from app.services.worker import process_email

    now = datetime.now(timezone.utc)
    attempts = 0
    while (result := await process_email(db, now)).processed:
        attempts += result.processed
    return attempts
