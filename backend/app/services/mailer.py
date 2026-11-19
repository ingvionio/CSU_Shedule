"""Отправка писем из очереди `email_outbox` через SMTP (Яндекс).

Письма сначала записываются в очередь вместе с обращением, а отправляются
отдельно. Поэтому недоступный SMTP не мешает сохранить обращение, а
неотправленные письма можно дослать командой `python -m app.cli send-emails`.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal

from sqlalchemy.orm import Session

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


def _send(item: EmailData) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_user))
    message["To"] = item.to_address
    if item.reply_to:
        message["Reply-To"] = item.reply_to
    message["Subject"] = item.subject
    message.set_content(item.body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as smtp:
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_one(item: EmailData) -> SendResult:
    """Отправляет одно письмо без обращения к БД."""
    settings = get_settings()
    if not settings.smtp_user:
        logger.info("Почта не настроена, письмо не отправлено: %s → %s\n%s", item.subject, item.to_address, item.body)
        return SendResult("skipped", "SMTP не настроен")
    try:
        _send(item)
    except (OSError, smtplib.SMTPException) as error:
        return SendResult("retry", str(error)[:500])
    return SendResult("sent")


def deliver(db: Session, items: list[EmailOutbox]) -> None:
    """Ручная отправка через тот же захват и обработчик, что у worker'а."""
    from app.services.worker import process_email

    ids = [item.id for item in items]
    now = datetime.now(timezone.utc)
    while process_email(db, now, ids=ids).processed:
        pass
    for item in items:
        db.refresh(item)


def deliver_pending(db: Session) -> int:
    """Досылает все письма, которые ещё не ушли. Возвращает число попыток."""
    from app.services.worker import process_email

    now = datetime.now(timezone.utc)
    attempts = 0
    while (result := process_email(db, now)).processed:
        attempts += result.processed
    return attempts
