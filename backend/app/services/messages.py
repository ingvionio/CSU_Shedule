"""Рассылка сообщений студентам: адресация, прочтение, очередь уведомлений."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Group, Message, MessageRecipient, PushDelivery, User
from app.schemas.message import MessageIn, PushStatsOut
from app.services import push, product_events

IMPORTANCE_HIGH = "high"
IMPORTANCE_LOW = "low"


class MessageError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _aware(value: datetime | None) -> datetime | None:
    """SQLite отдаёт время без пояса; в базе оно всегда UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def requires_ack(message: Message) -> bool:
    return message.importance == IMPORTANCE_HIGH


def is_unread(message: Message, recipient: MessageRecipient) -> bool:
    """Для важных непрочитанным считается всё, что не подтверждено «Ознакомлен»."""
    if requires_ack(message):
        return recipient.acknowledged_at is None
    return recipient.read_at is None


def _pending_condition():
    """SQL-версия `is_unread`."""
    return case(
        (Message.importance == IMPORTANCE_HIGH, MessageRecipient.acknowledged_at.is_(None)),
        else_=MessageRecipient.read_at.is_(None),
    )


async def target_title(db: AsyncSession, target: dict, group_names: dict[int, str] | None = None) -> str:
    """Адресация человеческими словами — для списка в админке."""
    kind = target["type"]
    if kind == "all":
        return "Все студенты"
    if kind == "course":
        return "Курс " + ", ".join(str(item) for item in sorted(target["courses"]))
    if kind == "direction":
        title = "Поток " + ", ".join(target["directions"])
        courses = target.get("courses") or []
        return title + (f" ({', '.join(str(item) for item in sorted(courses))} курс)" if courses else "")
    if kind == "group":
        if group_names is None:
            names = (await db.scalars(select(Group.name).where(Group.id.in_(target["group_ids"])).order_by(Group.name))).all()
        else:
            names = sorted(group_names[group_id] for group_id in set(target["group_ids"]) if group_id in group_names)
        return ("Группы " if len(names) > 1 else "Группа ") + ", ".join(names)
    return f"Студенты ({len(target['user_ids'])})"


async def target_titles(db: AsyncSession, messages: list[Message]) -> dict[int, str]:
    group_ids = {group_id for message in messages if message.target["type"] == "group"
                 for group_id in message.target["group_ids"]}
    names = dict((await db.execute(select(Group.id, Group.name).where(Group.id.in_(group_ids)))).all()) if group_ids else {}
    return {message.id: await target_title(db, message.target, names) for message in messages}


def _target_condition(target: dict):
    kind = target["type"]
    if kind == "all":
        return User.id.is_not(None)
    if kind == "course":
        return Group.course.in_(target["courses"])
    if kind == "direction":
        condition = Group.direction.in_(target["directions"])
        if target.get("courses"):
            condition = and_(condition, Group.course.in_(target["courses"]))
        return condition
    if kind == "group":
        return User.group_id.in_(target["group_ids"])
    return User.id.in_(target["user_ids"])


async def _matching_users(db: AsyncSession, target: dict) -> list[User]:
    query = select(User).outerjoin(Group, Group.id == User.group_id).where(_target_condition(target))
    return list((await db.scalars(query)).unique().all())


async def create_message(db: AsyncSession, data: MessageIn, admin: str, now: datetime | None = None, *, commit: bool = True) -> Message:
    """Сохраняет сообщение, получателей и очередь push одной транзакцией."""
    now = now or datetime.now(timezone.utc)
    target = data.target.model_dump(exclude_defaults=True)
    if target["type"] == "group" and await db.scalar(
        select(func.count(Group.id)).where(Group.id.in_(target["group_ids"]))
    ) != len(set(target["group_ids"])):
        raise MessageError("группа не найдена", 404)

    message = Message(
        title=data.title.strip(),
        body=data.body.strip(),
        importance=data.importance,
        target=target,
        created_by=admin,
        sent_at=now,
    )
    db.add(message)
    await db.flush()

    users = await _matching_users(db, target)
    db.add_all(
        MessageRecipient(message_id=message.id, user_id=user.id, group_id=user.group_id, created_at=now)
        for user in users
    )
    for user in users:
        product_events.add_event(db, product_events.MESSAGE_RECEIVED, user_id=user.id, now=now, message_id=message.id)
    if message.importance != IMPORTANCE_LOW and push.is_configured():
        await push.enqueue(db, message.id, [user.id for user in users], "message", now)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return message


async def attach_recent_messages(db: AsyncSession, user: User, now: datetime) -> list[int]:
    """Досылает студенту недавние сообщения его группе, курсу или потоку.

    Получатели — снимок на момент отправки, поэтому без этого студент,
    который поставил приложение на день позже, не увидел бы сообщение своей
    группе. Личные сообщения (`students`) не досылаются. Без коммита.
    """
    since = now - timedelta(days=get_settings().messages_late_join_days)
    already = select(MessageRecipient.message_id).where(MessageRecipient.user_id == user.id)
    candidates = (await db.scalars(
        select(Message).where(Message.deleted_at.is_(None), Message.sent_at >= since, Message.id.not_in(already))
    )).all()

    attached = []
    for message in candidates:
        if message.target["type"] == "students":
            continue
        match = await db.scalar(
            select(User.id)
            .outerjoin(Group, Group.id == User.group_id)
            .where(User.id == user.id, _target_condition(message.target))
        )
        if match is None:
            continue
        db.add(MessageRecipient(message_id=message.id, user_id=user.id, group_id=user.group_id, created_at=now))
        product_events.add_event(db, product_events.MESSAGE_RECEIVED, user_id=user.id, now=now, message_id=message.id)
        attached.append(message.id)
    await db.flush()
    return attached


# --- студент ---


def _inbox_query(user_id: int):
    return (
        select(MessageRecipient)
        .join(Message, Message.id == MessageRecipient.message_id)
        .where(MessageRecipient.user_id == user_id, Message.deleted_at.is_(None))
    )


async def inbox(db: AsyncSession, user_id: int) -> list[MessageRecipient]:
    query = _inbox_query(user_id).order_by(Message.sent_at.desc(), Message.id.desc())
    return list((await db.scalars(query)).unique().all())


async def unread_count(db: AsyncSession, user_id: int) -> int:
    query = (
        select(func.count(MessageRecipient.id))
        .join(Message, Message.id == MessageRecipient.message_id)
        .where(MessageRecipient.user_id == user_id, Message.deleted_at.is_(None), _pending_condition())
    )
    return await db.scalar(query) or 0


async def _recipient(db: AsyncSession, user_id: int, message_id: int) -> MessageRecipient:
    recipient = await db.scalar(_inbox_query(user_id).where(MessageRecipient.message_id == message_id))
    if recipient is None:
        raise MessageError("сообщение не найдено", 404)
    return recipient


async def open_message(db: AsyncSession, user_id: int, message_id: int, now: datetime | None = None) -> MessageRecipient:
    """Студент открыл сообщение — оно прочитано."""
    recipient = await _recipient(db, user_id, message_id)
    if recipient.read_at is None:
        recipient.read_at = now or datetime.now(timezone.utc)
        product_events.add_event(db, product_events.MESSAGE_READ, user_id=user_id, now=recipient.read_at, message_id=message_id)
        await db.commit()
    return recipient


async def acknowledge(db: AsyncSession, user_id: int, message_id: int, now: datetime | None = None) -> MessageRecipient:
    recipient = await _recipient(db, user_id, message_id)
    if not requires_ack(recipient.message):
        raise MessageError("это сообщение не требует подтверждения")
    now = now or datetime.now(timezone.utc)
    if recipient.read_at is None:
        product_events.add_event(db, product_events.MESSAGE_READ, user_id=user_id, now=now, message_id=message_id)
    if recipient.acknowledged_at is None:
        product_events.add_event(db, product_events.MESSAGE_ACK, user_id=user_id, now=now, message_id=message_id)
    recipient.read_at = recipient.read_at or now
    recipient.acknowledged_at = recipient.acknowledged_at or now
    await db.commit()
    return recipient


# --- методист ---


async def _get(db: AsyncSession, message_id: int) -> Message:
    message = await db.get(Message, message_id)
    if message is None or message.deleted_at is not None:
        raise MessageError("сообщение не найдено", 404)
    return message


async def admin_list(db: AsyncSession, include_automatic: bool = False) -> list[tuple[Message, int, int, int]]:
    """Сообщения с прогрессом: всего получателей, прочитали, подтвердили."""
    rows = (await db.execute(
        select(
            Message,
            func.count(MessageRecipient.id),
            func.count(MessageRecipient.read_at),
            func.count(MessageRecipient.acknowledged_at),
        )
        .outerjoin(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(Message.deleted_at.is_(None))
        .where(True if include_automatic else (Message.created_by.is_(None) | (Message.created_by != "system")))
        .group_by(Message.id)
        .order_by(Message.sent_at.desc(), Message.id.desc())
    )).all()
    return [tuple(row) for row in rows]


async def counts(db: AsyncSession, message_id: int) -> tuple[int, int, int]:
    row = (await db.execute(
        select(
            func.count(MessageRecipient.id),
            func.count(MessageRecipient.read_at),
            func.count(MessageRecipient.acknowledged_at),
        ).where(MessageRecipient.message_id == message_id)
    )).one()
    return tuple(row)


async def push_stats(db: AsyncSession, message_ids: list[int]) -> dict[int, PushStatsOut]:
    """Одна агрегирующая выборка на список сообщений, оба вида доставок."""
    configured = push.is_configured()
    stats = {message_id: PushStatsOut(configured=configured) for message_id in message_ids}
    if not message_ids:
        return stats
    rows = (await db.execute(
        select(
            PushDelivery.message_id,
            func.count(PushDelivery.id),
            func.sum(case((PushDelivery.status == "sent", 1), else_=0)),
            func.sum(case((PushDelivery.status == "pending", 1), else_=0)),
            func.sum(case((PushDelivery.status.in_(["failed", "gone", "skipped"]), 1), else_=0)),
        ).where(PushDelivery.message_id.in_(message_ids)).group_by(PushDelivery.message_id)
    )).all()
    for message_id, total, sent, pending, failed in rows:
        stats[message_id] = PushStatsOut(configured=configured, total=total, sent=sent, pending=pending, failed=failed)
    return stats


async def admin_detail(db: AsyncSession, message_id: int) -> tuple[Message, list[tuple[MessageRecipient, str | None]]]:
    message = await _get(db, message_id)
    rows = (await db.execute(
        select(MessageRecipient, Group.name)
        .outerjoin(Group, Group.id == MessageRecipient.group_id)
        .join(User, User.id == MessageRecipient.user_id)
        .where(MessageRecipient.message_id == message_id)
        .order_by(Group.name, User.full_name)
    )).unique().all()
    return message, [(recipient, group_name) for recipient, group_name in rows]


async def remind(db: AsyncSession, message_id: int, now: datetime | None = None) -> tuple[int, int]:
    """Записывает напоминание непрочитавшим и возвращает число студентов и устройств."""
    now = now or datetime.now(timezone.utc)
    message = await _get(db, message_id)
    if message.importance == IMPORTANCE_LOW:
        raise MessageError("у неважных сообщений нет напоминаний")

    cooldown = timedelta(hours=get_settings().remind_cooldown_hours)
    last = _aware(message.last_reminded_at)
    if last is not None and now - last < cooldown:
        hours = max(1, round((cooldown - (now - last)).total_seconds() / 3600))
        raise MessageError(f"напоминание уже отправлялось, следующее — примерно через {hours} ч", 429)

    pending = list(
        (await db.scalars(
            select(MessageRecipient)
            .join(Message, Message.id == MessageRecipient.message_id)
            .where(MessageRecipient.message_id == message_id, _pending_condition())
        )).unique().all()
    )
    if not pending:
        return 0, 0

    for recipient in pending:
        recipient.reminded_at = now
    message.last_reminded_at = now
    user_ids = [recipient.user_id for recipient in pending]
    devices = await push.enqueue(db, message.id, user_ids, "reminder", now) if push.is_configured() else 0
    await db.commit()
    return len(user_ids), devices


async def delete_message(db: AsyncSession, message_id: int, now: datetime | None = None) -> None:
    """Скрывает сообщение у всех. Отметки прочтения остаются в базе."""
    message = await _get(db, message_id)
    message.deleted_at = now or datetime.now(timezone.utc)
    await db.commit()


async def list_students(
    db: AsyncSession, query: str | None, course: int | None, group_id: int | None, limit: int = 50
) -> list[User]:
    statement = select(User).outerjoin(Group, Group.id == User.group_id)
    if query:
        statement = statement.where(func.lower(User.full_name).contains(query.strip().lower()))
    if course is not None:
        statement = statement.where(Group.course == course)
    if group_id is not None:
        statement = statement.where(User.group_id == group_id)
    return list((await db.scalars(statement.order_by(User.full_name).limit(limit))).unique().all())
