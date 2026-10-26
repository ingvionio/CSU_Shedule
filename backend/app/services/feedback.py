"""Обращения студентов: создание, папки админки, ответы, письма адресатам.

Студенты пока входят без аккаунта, поэтому автора узнаём по токену
устройства (храним хеш). Ответы студент видит в приложении по тому же
токену, а если оставил email — получает их и на почту.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    EmailOutbox,
    FeedbackKind,
    FeedbackMessage,
    FeedbackRecipient,
    FeedbackReply,
    FeedbackStatus,
    Group,
)
from app.schemas.feedback import FeedbackIn, FeedbackUpdateIn, RecipientUpdateIn

KIND_TITLES: dict[str, str] = {
    FeedbackKind.DEV.value: "Разработчики",
    FeedbackKind.METHODIST.value: "Методист",
    FeedbackKind.DEANERY.value: "Деканат",
    FeedbackKind.UNKNOWN.value: "Не распределено",
}

# Адресаты, которые заводятся сами при первом обращении к разделу.
DEFAULT_RECIPIENTS = [
    (FeedbackKind.DEV.value, "Команда разработчиков"),
    (FeedbackKind.METHODIST.value, "Методист"),
    (FeedbackKind.DEANERY.value, "Деканат"),
]

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FeedbackError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_email(value: str | None) -> bool:
    return bool(value and EMAIL_PATTERN.match(value.strip()))


def secret_hash(value: str) -> str:
    """Необратимый хеш токена или IP. Ключ — секрет приложения, чтобы IP нельзя было перебрать."""
    return hmac.new(get_settings().jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def ensure_recipients(db: Session) -> None:
    existing = set(db.scalars(select(FeedbackRecipient.kind)).all())
    missing = [(kind, title) for kind, title in DEFAULT_RECIPIENTS if kind not in existing]
    for order, (kind, title) in enumerate(missing):
        db.add(FeedbackRecipient(kind=kind, title=title, emails=[], is_active=True, sort_order=order))
    if missing:
        db.commit()


def list_recipients(db: Session) -> list[FeedbackRecipient]:
    ensure_recipients(db)
    return list(
        db.scalars(select(FeedbackRecipient).order_by(FeedbackRecipient.kind, FeedbackRecipient.sort_order)).all()
    )


def _route(db: Session, kind: str) -> FeedbackRecipient | None:
    """Адресат для папки. Для «Не знаю, кому» адресата нет — решает админ."""
    if kind == FeedbackKind.UNKNOWN.value:
        return None
    ensure_recipients(db)
    return db.scalar(
        select(FeedbackRecipient)
        .where(FeedbackRecipient.kind == kind, FeedbackRecipient.is_active.is_(True))
        .order_by(FeedbackRecipient.sort_order, FeedbackRecipient.id)
        .limit(1)
    )


def _app_link() -> str:
    url = get_settings().public_app_url.strip()
    return f"\n\nОткрыть приложение: {url}" if url else ""


def _enqueue_to_recipient(db: Session, message: FeedbackMessage) -> list[EmailOutbox]:
    recipient = message.recipient
    if recipient is None or not recipient.is_active:
        return []

    group = message.group.name if message.group else "группа не указана"
    author = message.author_name or "Без имени"
    contact = message.contact or "не указан"
    subject = f"[Расписание] Обращение №{message.id} · {recipient.title} · {group}"
    body = (
        f"Обращение №{message.id} для «{recipient.title}»\n"
        f"Группа: {group}\n"
        f"Автор: {author}\n"
        f"Контакт: {contact}\n\n"
        f"{message.text}\n\n"
        "—\n"
        + (
            "Ответить можно прямо на это письмо — ответ уйдёт студенту на почту. "
            "Чтобы студент увидел ответ в приложении, ответьте в админке."
            if is_email(message.contact)
            else "Студент не оставил почту — ответить можно в админке, ответ появится у него в приложении."
        )
        + _app_link()
    )
    reply_to = message.contact.strip() if is_email(message.contact) else None

    items = [
        EmailOutbox(message_id=message.id, to_address=address, reply_to=reply_to, subject=subject, body=body)
        for address in recipient.emails
    ]
    db.add_all(items)
    return items


def _enqueue_answer(db: Session, message: FeedbackMessage, reply: FeedbackReply) -> list[EmailOutbox]:
    if not is_email(message.contact):
        return []
    item = EmailOutbox(
        message_id=message.id,
        to_address=message.contact.strip(),
        subject=f"Ответ на ваше обращение №{message.id}",
        body=(
            f"{KIND_TITLES[message.kind]} ответил на ваше обращение:\n\n"
            f"{reply.text}\n\n"
            "—\n"
            f"Ваше обращение:\n{message.text}\n\n"
            "Ответ также виден в приложении расписания, в разделе «Вопросы»."
            + _app_link()
        ),
    )
    db.add(item)
    return [item]


def create_message(
    db: Session,
    data: FeedbackIn,
    token: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> tuple[FeedbackMessage, list[int]]:
    """Сохраняет обращение и ставит письма в очередь. Возвращает обращение и id писем."""
    if data.website:
        # Скрытое поле заполняют только боты.
        raise FeedbackError("обращение отклонено")

    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    token_hash = secret_hash(token) if token else None
    ip_hash = secret_hash(ip) if ip else None
    limits = (
        (FeedbackMessage.author_token_hash, token_hash, settings.feedback_rate_limit_per_hour),
        (FeedbackMessage.ip_hash, ip_hash, settings.feedback_ip_rate_limit_per_hour),
    )
    for column, value, limit in limits:
        if value is None:
            continue
        recent = db.scalar(
            select(func.count(FeedbackMessage.id)).where(
                column == value, FeedbackMessage.created_at >= now - timedelta(hours=1)
            )
        )
        if recent >= limit:
            raise FeedbackError("слишком много обращений, попробуйте через час", 429)

    if data.group_id is not None and db.get(Group, data.group_id) is None:
        raise FeedbackError("группа не найдена", 404)

    message = FeedbackMessage(
        kind=data.kind,
        recipient=_route(db, data.kind),
        text=data.text.strip(),
        group_id=data.group_id,
        author_name=(data.author_name or "").strip() or None,
        contact=(data.contact or "").strip() or None,
        author_token_hash=token_hash,
        ip_hash=ip_hash,
        status=FeedbackStatus.NEW.value,
        created_at=now,
    )
    db.add(message)
    db.flush()
    db.refresh(message, ["group"])

    outbox = _enqueue_to_recipient(db, message)
    db.commit()
    return message, [item.id for item in outbox]


def list_for_token(db: Session, token: str) -> list[FeedbackMessage]:
    return list(
        db.scalars(
            select(FeedbackMessage)
            .where(FeedbackMessage.author_token_hash == secret_hash(token))
            .order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
        ).all()
    )


def admin_list(db: Session, kind: str | None, status: str | None) -> list[FeedbackMessage]:
    query = select(FeedbackMessage).order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
    if kind:
        query = query.where(FeedbackMessage.kind == kind)
    if status:
        query = query.where(FeedbackMessage.status == status)
    return list(db.scalars(query).all())


def folder_summary(db: Session) -> dict[str, dict[str, int]]:
    """Число обращений по папкам: всего и новых."""
    rows = db.execute(
        select(FeedbackMessage.kind, FeedbackMessage.status, func.count(FeedbackMessage.id)).group_by(
            FeedbackMessage.kind, FeedbackMessage.status
        )
    ).all()
    summary = {kind: {"total": 0, "new": 0} for kind in KIND_TITLES}
    for kind, status, count in rows:
        summary[kind]["total"] += count
        if status == FeedbackStatus.NEW.value:
            summary[kind]["new"] += count
    return summary


def _get(db: Session, message_id: int) -> FeedbackMessage:
    message = db.get(FeedbackMessage, message_id)
    if message is None:
        raise FeedbackError("обращение не найдено", 404)
    return message


def update_message(db: Session, message_id: int, data: FeedbackUpdateIn) -> tuple[FeedbackMessage, list[int]]:
    """Статус, заметка и перенос в другую папку. При переносе письмо уходит новому адресату."""
    message = _get(db, message_id)
    outbox: list[EmailOutbox] = []

    if data.kind is not None and data.kind != message.kind:
        message.kind = data.kind
        message.recipient = _route(db, data.kind)
        outbox = _enqueue_to_recipient(db, message)
    if data.status is not None:
        message.status = data.status
    if data.admin_note is not None:
        message.admin_note = data.admin_note.strip() or None

    db.commit()
    return message, [item.id for item in outbox]


def add_reply(db: Session, message_id: int, text: str, admin: str) -> tuple[FeedbackMessage, list[int]]:
    message = _get(db, message_id)
    reply = FeedbackReply(author_kind="staff", author_name=admin, text=text.strip())
    message.replies.append(reply)
    message.status = FeedbackStatus.ANSWERED.value
    db.flush()

    outbox = _enqueue_answer(db, message, reply)
    db.commit()
    db.refresh(message)
    return message, [item.id for item in outbox]


def update_recipient(db: Session, recipient_id: int, data: RecipientUpdateIn) -> FeedbackRecipient:
    recipient = db.get(FeedbackRecipient, recipient_id)
    if recipient is None:
        raise FeedbackError("адресат не найден", 404)

    if data.emails is not None:
        emails = list(dict.fromkeys(address.strip().lower() for address in data.emails if address.strip()))
        wrong = [address for address in emails if not is_email(address)]
        if wrong:
            raise FeedbackError(f"неверный email: {', '.join(wrong)}", 422)
        recipient.emails = emails
    if data.title is not None:
        recipient.title = data.title.strip() or recipient.title
    if data.is_active is not None:
        recipient.is_active = data.is_active

    db.commit()
    return recipient
