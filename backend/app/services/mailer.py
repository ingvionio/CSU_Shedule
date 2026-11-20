"""Отправка писем из очереди `email_outbox` через SMTP (Яндекс).

Письма сначала записываются в очередь вместе с обращением, а отправляются
отдельно. Поэтому недоступный SMTP не мешает сохранить обращение, а
неотправленные письма можно дослать командой `python -m app.cli send-emails`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr

from aiosmtplib import send
from aiosmtplib.errors import SMTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import EmailOutbox, EmailStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


async def _send(item: EmailOutbox) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_user))
    message["To"] = item.to_address
    if item.reply_to:
        message["Reply-To"] = item.reply_to
    message["Subject"] = item.subject
    message.set_content(item.body)

    await send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=True,
        timeout=20,
    )


async def deliver(db: AsyncSession, items: list[EmailOutbox]) -> None:
    """Отправляет письма и записывает результат. Ошибки не пробрасывает."""
    settings = get_settings()
    for item in items:
        if not settings.smtp_user:
            logger.info("Почта не настроена, письмо не отправлено: %s → %s\n%s", item.subject, item.to_address, item.body)
            item.status = EmailStatus.SKIPPED.value
            continue

        item.attempts += 1
        try:
            await _send(item)
        except (OSError, SMTPException) as error:
            logger.warning("Письмо %s на %s не отправлено: %s", item.id, item.to_address, error)
            item.last_error = str(error)[:500]
            if item.attempts >= MAX_ATTEMPTS:
                item.status = EmailStatus.FAILED.value
        else:
            item.status = EmailStatus.SENT.value
            item.sent_at = datetime.now(timezone.utc)
            item.last_error = None
    await db.commit()


async def deliver_by_ids(ids: list[int]) -> None:
    """Фоновая задача после ответа API: своя сессия, потому что запросная уже закрыта."""
    if not ids:
        return
    async with SessionLocal() as db:
        items = list(await db.scalars(select(EmailOutbox).where(EmailOutbox.id.in_(ids))))
        # Возвращаем соединение в пул перед обращением к SMTP.
        await db.commit()
        await deliver(db, items)


async def deliver_pending(db: AsyncSession) -> int:
    """Досылает все письма, которые ещё не ушли. Возвращает число попыток."""
    items = list(await db.scalars(select(EmailOutbox).where(EmailOutbox.status == EmailStatus.PENDING.value)))
    await db.commit()
    await deliver(db, items)
    return len(items)
