"""Обращения студентов: создание, папки админки, ответы и почта."""

from __future__ import annotations

from collections import Counter

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.errors import HeaderParseError
from email.headerregistry import Address
from pathlib import PurePath

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

from app.core.config import get_settings
from app.models import (
    EmailOutbox,
    FeedbackAttachment,
    FeedbackKind,
    FeedbackMessage,
    FeedbackRecipient,
    FeedbackReply,
    FeedbackStatus,
    Group,
    User,
)
from app.schemas.feedback import CertificateRequestIn, FeedbackIn, FeedbackSubmission, FeedbackUpdateIn, RecipientUpdateIn

KIND_TITLES: dict[str, str] = {
    FeedbackKind.DEV.value: "Разработчики",
    FeedbackKind.METHODIST.value: "Методист",
    FeedbackKind.DEANERY.value: "Деканат",
    FeedbackKind.UNKNOWN.value: "Не распределено",
    FeedbackKind.CERTIFICATE.value: "Справка",
}

# Адресаты, которые заводятся сами при первом обращении к разделу.
DEFAULT_RECIPIENTS = [
    (FeedbackKind.DEV.value, "Команда разработчиков"),
    (FeedbackKind.METHODIST.value, "Методист"),
    (FeedbackKind.DEANERY.value, "Деканат"),
]

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DUPLICATE_SECONDS = 60

DELIVERY_TITLES: dict[str, str] = {
    "pickup": "Заберу лично в учебной части",
    "scan": "Требуется скан на эл.почту",
    "post": "Отправить почтой РФ",
}

# Файлы к ответам: сканы справок и документы. Тип берётся по расширению, а не от клиента.
ATTACHMENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
}
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
# Яндекс принимает письма до 30 МБ, а base64 увеличивает вложения на треть.
MAX_ATTACHMENTS_TOTAL = 20 * 1024 * 1024


@dataclass(frozen=True)
class AttachmentIn:
    filename: str
    data: bytes


def recipient_kind(kind: str) -> str:
    return FeedbackKind.METHODIST.value if kind == FeedbackKind.CERTIFICATE.value else kind


class FeedbackError(Exception):
    def __init__(self, message: str, status_code: int = 400, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def is_email(value: str | None) -> bool:
    if not value or not EMAIL_PATTERN.fullmatch(value.strip()):
        return False
    try:
        address = Address(addr_spec=value.strip())
    except (ValueError, HeaderParseError):
        return False
    return address.addr_spec == value.strip()


def secret_hash(value: str) -> str:
    """Необратимый хеш токена или IP. Ключ — секрет приложения, чтобы IP нельзя было перебрать."""
    return hmac.new(get_settings().jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


async def ensure_recipients(db: AsyncSession) -> None:
    existing = set((await db.scalars(select(FeedbackRecipient.kind))).all())
    if all(kind in existing for kind, _ in DEFAULT_RECIPIENTS):
        return
    if db.get_bind().dialect.name == "postgresql":
        await _lock(db, "recipients")
        existing = set((await db.scalars(select(FeedbackRecipient.kind))).all())
    missing = [(kind, title) for kind, title in DEFAULT_RECIPIENTS if kind not in existing]
    for order, (kind, title) in enumerate(missing):
        db.add(FeedbackRecipient(kind=kind, title=title, emails=[], is_active=True, sort_order=order))
    await db.flush()


async def list_recipients(db: AsyncSession) -> list[FeedbackRecipient]:
    await ensure_recipients(db)
    await db.commit()
    return list(
        (await db.scalars(select(FeedbackRecipient).order_by(FeedbackRecipient.kind, FeedbackRecipient.sort_order))).all()
    )


async def _route(db: AsyncSession, kind: str) -> FeedbackRecipient | None:
    """Адресат для папки. Для «Не знаю, кому» адресата нет — решает админ."""
    if kind == FeedbackKind.UNKNOWN.value:
        return None
    await ensure_recipients(db)
    recipients = select(FeedbackRecipient).where(FeedbackRecipient.kind == recipient_kind(kind))
    if kind != FeedbackKind.CERTIFICATE.value:
        recipients = recipients.where(FeedbackRecipient.is_active.is_(True))
    return await db.scalar(
        recipients.order_by(FeedbackRecipient.is_active.desc(), FeedbackRecipient.sort_order, FeedbackRecipient.id)
        .limit(1)
    )


def _app_link() -> str:
    url = get_settings().public_app_url.strip()
    return f"\n\nОткрыть приложение: {url}" if url else ""


def certificate_letter(message: FeedbackMessage) -> tuple[str, str]:
    """Тема и текст письма методисту в формате заявки учебной части."""
    group = message.group.name if message.group else "группа не указана"
    author = message.author_name or "Без имени"
    delivery = DELIVERY_TITLES.get(message.certificate_delivery or "", "Способ получения не указан")
    if message.certificate_delivery == "post" and message.certificate_address:
        delivery = f"{delivery}, адрес: {message.certificate_address}"
    elif message.certificate_delivery == "scan" and message.contact:
        delivery = f"{delivery}: {message.contact}"
    lines = [
        "Заявка на справку о том, что студент.",
        f"1. {author}",
        f"2. {group}",
        f"3. {message.certificate_purpose or '—'}",
        f"4. Кол-во: {message.certificate_copies or '—'} шт.",
        f"5. {delivery}",
    ]
    if message.text:
        lines += ["", f"Дополнительно: {message.text}"]
    lines += [
        "",
        "—",
        f"Заявка №{message.id} из приложения расписания ИИТ.",
        "Ответить студенту и приложить скан справки можно в админке, в папке «Справки»: "
        "ответ появится у студента в приложении"
        + (" и придёт ему на почту." if is_email(message.contact) else "."),
    ]
    subject = f"[Расписание] Заявка на справку №{message.id} · {group} · {author}"
    return subject, "\n".join(lines) + _app_link()


def _enqueue_to_recipient(db: AsyncSession, message: FeedbackMessage) -> list[EmailOutbox]:
    recipient = message.recipient
    if recipient is None or not recipient.is_active:
        return []
    reply_to = message.contact.strip() if is_email(message.contact) else None

    if message.kind == FeedbackKind.CERTIFICATE.value:
        subject, body = certificate_letter(message)
        items = [
            EmailOutbox(message_id=message.id, to_address=address, reply_to=reply_to, subject=subject, body=body)
            for address in recipient.emails
        ]
        db.add_all(items)
        return items

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

    items = [
        EmailOutbox(message_id=message.id, to_address=address, reply_to=reply_to, subject=subject, body=body)
        for address in recipient.emails
    ]
    db.add_all(items)
    return items


def _enqueue_answer(db: AsyncSession, message: FeedbackMessage, reply: FeedbackReply) -> list[EmailOutbox]:
    if not is_email(message.contact):
        return []
    is_certificate = message.kind == FeedbackKind.CERTIFICATE.value
    what = "вашу заявку на справку" if is_certificate else "ваше обращение"
    original = f"Справка: {message.certificate_purpose or '—'}" if is_certificate else f"Ваше обращение:\n{message.text}"
    files = "\n\nВо вложении: " + ", ".join(item.filename for item in reply.attachments) if reply.attachments else ""
    item = EmailOutbox(
        message_id=message.id,
        reply_id=reply.id if reply.attachments else None,
        to_address=message.contact.strip(),
        subject=f"Ответ на {what} №{message.id}",
        body=(
            f"{KIND_TITLES[recipient_kind(message.kind)]} ответил на {what}:\n\n"
            f"{reply.text}{files}\n\n"
            "—\n"
            f"{original}\n\n"
            "Ответ также виден в приложении расписания, в разделе «Мои обращения»."
            + _app_link()
        ),
    )
    db.add(item)
    return [item]


async def create_message(
    db: AsyncSession,
    data: FeedbackSubmission,
    ip: str | None,
    *,
    author: User,
    now: datetime | None = None,
) -> tuple[FeedbackMessage, list[int]]:
    """Сохраняет обращение и ставит письма в очередь. Возвращает обращение и id писем.

    Обращение подписывается ФИО студента из профиля Moodle.
    """
    if data.website:
        # Скрытое поле заполняют только боты.
        raise FeedbackError("обращение отклонено")

    is_certificate = isinstance(data, CertificateRequestIn)
    if is_certificate and author.group_id is None:
        raise FeedbackError("В профиле Moodle не указана учебная группа", 409)
    purpose = data.purpose if is_certificate else None
    copies = data.copies if is_certificate else None
    delivery = data.delivery if is_certificate else None
    address = data.address if is_certificate else None

    settings = get_settings()
    ip_hash = secret_hash(ip) if ip else None
    if db.get_bind().dialect.name == "postgresql":
        if ip_hash is not None:
            await _lock(db, f"ip:{ip_hash}")
        await _lock(db, f"author:{author.id}")
    else:
        # SQLite сериализует запись до проверки лимита.
        await db.execute(update(User).where(User.id == author.id).values(id=User.id))
    now = now or datetime.now(timezone.utc)
    limits = (
        (FeedbackMessage.author_id, author.id, settings.feedback_rate_limit_per_hour),
        (FeedbackMessage.ip_hash, ip_hash, settings.feedback_ip_rate_limit_per_hour),
    )
    for column, value, limit in limits:
        if value is None:
            continue
        recent = await db.scalar(
            select(func.count(FeedbackMessage.id)).where(
                column == value, FeedbackMessage.created_at >= now - timedelta(hours=1)
            )
        )
        if recent >= limit:
            raise FeedbackError("слишком много обращений, попробуйте через час", 429, 3600)

    duplicate = await db.scalar(select(FeedbackMessage.id).where(
        FeedbackMessage.author_id == author.id,
        FeedbackMessage.kind == data.kind,
        FeedbackMessage.text == data.text,
        FeedbackMessage.certificate_purpose == purpose,
        FeedbackMessage.certificate_copies == copies,
        FeedbackMessage.created_at >= now - timedelta(seconds=DUPLICATE_SECONDS),
    ).limit(1))
    if duplicate is not None:
        raise FeedbackError("такое обращение уже отправлено", 429, DUPLICATE_SECONDS)

    if isinstance(data, FeedbackIn) and data.group_id is not None and await db.get(Group, data.group_id) is None:
        raise FeedbackError("группа не найдена", 404)

    contact = data.contact.strip() if isinstance(data, FeedbackIn) and data.contact else None
    if is_certificate:
        if data.email and not is_email(data.email):
            raise FeedbackError("Проверьте адрес почты", 422)
        contact = data.email
    message = FeedbackMessage(
        kind=data.kind,
        recipient=await _route(db, data.kind),
        text=data.text,
        certificate_purpose=purpose,
        certificate_copies=copies,
        certificate_delivery=delivery,
        certificate_address=address,
        group_id=author.group_id,
        author_name=author.full_name,
        author_id=author.id,
        contact=contact or None,
        ip_hash=ip_hash,
        status=FeedbackStatus.NEW.value,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message, ["group"])

    outbox = _enqueue_to_recipient(db, message)
    await db.commit()
    return message, [item.id for item in outbox]


async def _lock(db: AsyncSession, scope: str) -> None:
    key = int.from_bytes(hashlib.sha256(f"feedback:{scope}".encode()).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(key)))


async def list_for_student(db: AsyncSession, author_id: int) -> list[FeedbackMessage]:
    return list(
        (await db.scalars(
            select(FeedbackMessage)
            .where(FeedbackMessage.author_id == author_id)
            .order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc())
        )).all()
    )


async def admin_list(db: AsyncSession, kind: str | None, status: str | None, limit: int, before_id: int | None) -> list[FeedbackMessage]:
    query = select(FeedbackMessage).order_by(FeedbackMessage.created_at.desc(), FeedbackMessage.id.desc()).limit(limit)
    if kind:
        query = query.where(FeedbackMessage.kind == kind)
    if status:
        query = query.where(FeedbackMessage.status == status)
    if before_id is not None:
        cursor = select(FeedbackMessage.created_at, FeedbackMessage.id).where(FeedbackMessage.id == before_id)
        query = query.where(tuple_(FeedbackMessage.created_at, FeedbackMessage.id) < cursor.scalar_subquery())
    return list((await db.scalars(query)).all())


async def folder_summary(db: AsyncSession) -> dict[str, dict[str, int]]:
    """Число обращений по папкам: всего и новых."""
    rows = (await db.execute(
        select(FeedbackMessage.kind, FeedbackMessage.status, func.count(FeedbackMessage.id)).group_by(
            FeedbackMessage.kind, FeedbackMessage.status
        )
    )).all()
    summary = {kind: {"total": 0, "new": 0} for kind in KIND_TITLES}
    for kind, status, count in rows:
        summary[kind]["total"] += count
        if status == FeedbackStatus.NEW.value:
            summary[kind]["new"] += count
    return summary


async def _get(db: AsyncSession, message_id: int) -> FeedbackMessage:
    message = await db.get(FeedbackMessage, message_id)
    if message is None:
        raise FeedbackError("обращение не найдено", 404)
    return message


async def update_message(db: AsyncSession, message_id: int, data: FeedbackUpdateIn) -> tuple[FeedbackMessage, list[int]]:
    """Статус, заметка и перенос в другую папку. При переносе письмо уходит новому адресату."""
    message = await _get(db, message_id)
    outbox: list[EmailOutbox] = []

    if data.kind is not None and data.kind != message.kind:
        if message.kind == FeedbackKind.CERTIFICATE.value:
            raise FeedbackError("Заказ справки нельзя перенести в другую папку", 422)
        message.kind = data.kind
        message.recipient = await _route(db, data.kind)
        outbox = _enqueue_to_recipient(db, message)
    if data.status is not None:
        message.status = data.status
    if data.admin_note is not None:
        message.admin_note = data.admin_note.strip() or None

    await db.commit()
    return message, [item.id for item in outbox]


def _clean_filename(name: str, suffix: str) -> str:
    """Имя без пути и управляющих символов: оно попадёт в заголовки письма и ответа."""
    stem = PurePath(name.replace("\\", "/")).name
    stem = "".join(char for char in unicodedata.normalize("NFC", stem) if unicodedata.category(char)[0] != "C")
    stem = stem.strip().strip(".") or "файл"
    if not stem.lower().endswith(suffix):
        stem += suffix
    return stem if len(stem) <= 200 else stem[: 200 - len(suffix)] + suffix


def check_attachments(files: list[AttachmentIn]) -> list[FeedbackAttachment]:
    if len(files) > MAX_ATTACHMENTS:
        raise FeedbackError(f"Можно приложить не больше {MAX_ATTACHMENTS} файлов", 422)
    if sum(len(item.data) for item in files) > MAX_ATTACHMENTS_TOTAL:
        raise FeedbackError("Файлы вместе больше 20 МБ — письмо с ними не дойдёт", 413)
    result = []
    for item in files:
        name = item.filename[:100]
        suffix = PurePath(item.filename.replace("\\", "/")).suffix.lower()
        content_type = ATTACHMENT_TYPES.get(suffix)
        if content_type is None:
            raise FeedbackError(f"Файл «{name}»: можно PDF, фото (JPG, PNG, HEIC) или документ Word", 422)
        if not item.data:
            raise FeedbackError(f"Файл «{name}» пустой", 422)
        if len(item.data) > MAX_ATTACHMENT_BYTES:
            raise FeedbackError(f"Файл «{name}» больше 10 МБ", 413)
        result.append(FeedbackAttachment(
            filename=_clean_filename(item.filename, suffix), content_type=content_type,
            size=len(item.data), data=item.data,
        ))
    return result


async def add_reply(
    db: AsyncSession, message_id: int, text: str, admin: str, files: list[AttachmentIn] | None = None,
) -> tuple[FeedbackMessage, list[int]]:
    attachments = check_attachments(files or [])
    text = text.strip()
    if not text and not attachments:
        raise FeedbackError("Введите текст ответа или приложите файл", 422)
    message = await _get(db, message_id)
    reply = FeedbackReply(author_kind="staff", author_name=admin, text=text, attachments=attachments)
    message.replies.append(reply)
    message.status = FeedbackStatus.ANSWERED.value
    await db.flush()

    outbox = _enqueue_answer(db, message, reply)
    await db.commit()
    # Перечитываем переписку целиком: у ответов после commit нужны и файлы.
    message = await db.scalar(
        select(FeedbackMessage).where(FeedbackMessage.id == message_id)
        .options(selectinload(FeedbackMessage.replies).selectinload(FeedbackReply.attachments))
        .execution_options(populate_existing=True)
    )
    return message, [item.id for item in outbox]


async def update_recipient(db: AsyncSession, recipient_id: int, data: RecipientUpdateIn) -> FeedbackRecipient:
    recipient = await db.get(FeedbackRecipient, recipient_id)
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

    await db.commit()
    return recipient


async def fill_authors_from_devices(db: AsyncSession, apply: bool) -> list[tuple[int, str]]:
    """Подписывает старые безымянные обращения ФИО студента, который потом вошёл через Moodle с того же устройства.

    Совпадение — по хешу ключа устройства: им подписано обращение и его же хранит профиль
    после входа. Профиль помнит только последнее устройство, поэтому подпишутся не все.
    Трогаются только обращения без имени. Возвращает (id обращения, ФИО).
    """
    rows = (
        await db.execute(
            select(FeedbackMessage, User)
            .join(User, User.device_key_hash == FeedbackMessage.author_token_hash)
            .where(FeedbackMessage.author_name.is_(None), User.role == "student")
            .order_by(FeedbackMessage.id)
        )
    ).all()
    matches = Counter(message.id for message, _ in rows)
    filled: list[tuple[int, str]] = []
    for message, user in rows:
        # Один ключ устройства у нескольких профилей — непонятно, кто писал; не подписываем.
        if matches[message.id] > 1:
            continue
        filled.append((message.id, user.full_name))
        if apply:
            message.author_name = user.full_name
            if message.group_id is None:
                message.group_id = user.group_id
    if apply:
        await db.commit()
    return filled


async def get_attachment(db: AsyncSession, attachment_id: int, author_id: int | None = None) -> FeedbackAttachment:
    """Файл с содержимым. С author_id — только из обращений этого студента."""
    query = (
        select(FeedbackAttachment)
        .options(undefer(FeedbackAttachment.data))
        .join(FeedbackReply, FeedbackReply.id == FeedbackAttachment.reply_id)
        .join(FeedbackMessage, FeedbackMessage.id == FeedbackReply.message_id)
        .where(FeedbackAttachment.id == attachment_id)
    )
    if author_id is not None:
        query = query.where(FeedbackMessage.author_id == author_id)
    attachment = await db.scalar(query)
    if attachment is None:
        raise FeedbackError("файл не найден", 404)
    return attachment


async def reply_files(db: AsyncSession, reply_id: int) -> list[tuple[str, str, bytes]]:
    """Вложения письма: (имя, тип, содержимое)."""
    rows = await db.scalars(
        select(FeedbackAttachment).options(undefer(FeedbackAttachment.data))
        .where(FeedbackAttachment.reply_id == reply_id).order_by(FeedbackAttachment.id)
    )
    return [(item.filename, item.content_type, item.data) for item in rows]
