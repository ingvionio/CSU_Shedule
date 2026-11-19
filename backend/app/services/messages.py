"""Рассылка сообщений студентам: адресация, прочтение, очередь уведомлений."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Group, Message, MessageRecipient, PushDelivery, User
from app.schemas.message import MessageIn, PushStatsOut
from app.services import push

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


def target_title(db: Session, target: dict, group_names: dict[int, str] | None = None) -> str:
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
            names = db.scalars(select(Group.name).where(Group.id.in_(target["group_ids"])).order_by(Group.name)).all()
        else:
            names = sorted(group_names[group_id] for group_id in set(target["group_ids"]) if group_id in group_names)
        return ("Группы " if len(names) > 1 else "Группа ") + ", ".join(names)
    return f"Студенты ({len(target['user_ids'])})"


def target_titles(db: Session, messages: list[Message]) -> dict[int, str]:
    group_ids = {group_id for message in messages if message.target["type"] == "group"
                 for group_id in message.target["group_ids"]}
    names = dict(db.execute(select(Group.id, Group.name).where(Group.id.in_(group_ids))).all()) if group_ids else {}
    return {message.id: target_title(db, message.target, names) for message in messages}


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


def _matching_users(db: Session, target: dict) -> list[User]:
    query = select(User).outerjoin(Group, Group.id == User.group_id).where(_target_condition(target))
    return list(db.scalars(query).unique().all())


def create_message(db: Session, data: MessageIn, admin: str, now: datetime | None = None) -> Message:
    """Сохраняет сообщение, получателей и очередь push одной транзакцией."""
    now = now or datetime.now(timezone.utc)
    target = data.target.model_dump(exclude_defaults=True)
    if target["type"] == "group" and db.scalar(
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
    db.flush()

    users = _matching_users(db, target)
    db.add_all(
        MessageRecipient(message_id=message.id, user_id=user.id, group_id=user.group_id, created_at=now)
        for user in users
    )
    if message.importance != IMPORTANCE_LOW and push.is_configured():
        push.enqueue(db, message.id, [user.id for user in users], "message", now)
    db.commit()
    return message


def attach_recent_messages(db: Session, user: User, now: datetime) -> list[int]:
    """Досылает студенту недавние сообщения его группе, курсу или потоку.

    Получатели — снимок на момент отправки, поэтому без этого студент,
    который поставил приложение на день позже, не увидел бы сообщение своей
    группе. Личные сообщения (`students`) не досылаются. Без коммита.
    """
    since = now - timedelta(days=get_settings().messages_late_join_days)
    already = select(MessageRecipient.message_id).where(MessageRecipient.user_id == user.id)
    candidates = db.scalars(
        select(Message).where(Message.deleted_at.is_(None), Message.sent_at >= since, Message.id.not_in(already))
    ).all()

    attached = []
    for message in candidates:
        if message.target["type"] == "students":
            continue
        match = db.scalar(
            select(User.id)
            .outerjoin(Group, Group.id == User.group_id)
            .where(User.id == user.id, _target_condition(message.target))
        )
        if match is None:
            continue
        db.add(MessageRecipient(message_id=message.id, user_id=user.id, group_id=user.group_id, created_at=now))
        attached.append(message.id)
    db.flush()
    return attached


# --- студент ---


def _inbox_query(user_id: int):
    return (
        select(MessageRecipient)
        .join(Message, Message.id == MessageRecipient.message_id)
        .where(MessageRecipient.user_id == user_id, Message.deleted_at.is_(None))
    )


def inbox(db: Session, user_id: int) -> list[MessageRecipient]:
    query = _inbox_query(user_id).order_by(Message.sent_at.desc(), Message.id.desc())
    return list(db.scalars(query).unique().all())


def unread_count(db: Session, user_id: int) -> int:
    query = (
        select(func.count(MessageRecipient.id))
        .join(Message, Message.id == MessageRecipient.message_id)
        .where(MessageRecipient.user_id == user_id, Message.deleted_at.is_(None), _pending_condition())
    )
    return db.scalar(query) or 0


def _recipient(db: Session, user_id: int, message_id: int) -> MessageRecipient:
    recipient = db.scalar(_inbox_query(user_id).where(MessageRecipient.message_id == message_id))
    if recipient is None:
        raise MessageError("сообщение не найдено", 404)
    return recipient


def open_message(db: Session, user_id: int, message_id: int, now: datetime | None = None) -> MessageRecipient:
    """Студент открыл сообщение — оно прочитано."""
    recipient = _recipient(db, user_id, message_id)
    if recipient.read_at is None:
        recipient.read_at = now or datetime.now(timezone.utc)
        db.commit()
    return recipient


def acknowledge(db: Session, user_id: int, message_id: int, now: datetime | None = None) -> MessageRecipient:
    recipient = _recipient(db, user_id, message_id)
    if not requires_ack(recipient.message):
        raise MessageError("это сообщение не требует подтверждения")
    now = now or datetime.now(timezone.utc)
    recipient.read_at = recipient.read_at or now
    recipient.acknowledged_at = recipient.acknowledged_at or now
    db.commit()
    return recipient


# --- методист ---


def _get(db: Session, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if message is None or message.deleted_at is not None:
        raise MessageError("сообщение не найдено", 404)
    return message


def admin_list(db: Session) -> list[tuple[Message, int, int, int]]:
    """Сообщения с прогрессом: всего получателей, прочитали, подтвердили."""
    rows = db.execute(
        select(
            Message,
            func.count(MessageRecipient.id),
            func.count(MessageRecipient.read_at),
            func.count(MessageRecipient.acknowledged_at),
        )
        .outerjoin(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(Message.deleted_at.is_(None))
        .group_by(Message.id)
        .order_by(Message.sent_at.desc(), Message.id.desc())
    ).all()
    return [tuple(row) for row in rows]


def counts(db: Session, message_id: int) -> tuple[int, int, int]:
    row = db.execute(
        select(
            func.count(MessageRecipient.id),
            func.count(MessageRecipient.read_at),
            func.count(MessageRecipient.acknowledged_at),
        ).where(MessageRecipient.message_id == message_id)
    ).one()
    return tuple(row)


def push_stats(db: Session, message_ids: list[int]) -> dict[int, PushStatsOut]:
    """Одна агрегирующая выборка на список сообщений, оба вида доставок."""
    configured = push.is_configured()
    stats = {message_id: PushStatsOut(configured=configured) for message_id in message_ids}
    if not message_ids:
        return stats
    rows = db.execute(
        select(
            PushDelivery.message_id,
            func.count(PushDelivery.id),
            func.sum(case((PushDelivery.status == "sent", 1), else_=0)),
            func.sum(case((PushDelivery.status == "pending", 1), else_=0)),
            func.sum(case((PushDelivery.status.in_(["failed", "gone", "skipped"]), 1), else_=0)),
        ).where(PushDelivery.message_id.in_(message_ids)).group_by(PushDelivery.message_id)
    ).all()
    for message_id, total, sent, pending, failed in rows:
        stats[message_id] = PushStatsOut(configured=configured, total=total, sent=sent, pending=pending, failed=failed)
    return stats


def admin_detail(db: Session, message_id: int) -> tuple[Message, list[tuple[MessageRecipient, str | None]]]:
    message = _get(db, message_id)
    rows = db.execute(
        select(MessageRecipient, Group.name)
        .outerjoin(Group, Group.id == MessageRecipient.group_id)
        .join(User, User.id == MessageRecipient.user_id)
        .where(MessageRecipient.message_id == message_id)
        .order_by(Group.name, User.full_name)
    ).unique().all()
    return message, [(recipient, group_name) for recipient, group_name in rows]


def remind(db: Session, message_id: int, now: datetime | None = None) -> tuple[int, int]:
    """Записывает напоминание непрочитавшим и возвращает число студентов и устройств."""
    now = now or datetime.now(timezone.utc)
    message = _get(db, message_id)
    if message.importance == IMPORTANCE_LOW:
        raise MessageError("у неважных сообщений нет напоминаний")

    cooldown = timedelta(hours=get_settings().remind_cooldown_hours)
    last = _aware(message.last_reminded_at)
    if last is not None and now - last < cooldown:
        hours = max(1, round((cooldown - (now - last)).total_seconds() / 3600))
        raise MessageError(f"напоминание уже отправлялось, следующее — примерно через {hours} ч", 429)

    pending = list(
        db.scalars(
            select(MessageRecipient)
            .join(Message, Message.id == MessageRecipient.message_id)
            .where(MessageRecipient.message_id == message_id, _pending_condition())
        ).unique().all()
    )
    if not pending:
        return 0, 0

    for recipient in pending:
        recipient.reminded_at = now
    message.last_reminded_at = now
    user_ids = [recipient.user_id for recipient in pending]
    devices = push.enqueue(db, message.id, user_ids, "reminder", now) if push.is_configured() else 0
    db.commit()
    return len(user_ids), devices


def delete_message(db: Session, message_id: int, now: datetime | None = None) -> None:
    """Скрывает сообщение у всех. Отметки прочтения остаются в базе."""
    message = _get(db, message_id)
    message.deleted_at = now or datetime.now(timezone.utc)
    db.commit()


def list_students(
    db: Session, query: str | None, course: int | None, group_id: int | None, limit: int = 50
) -> list[User]:
    statement = select(User).outerjoin(Group, Group.id == User.group_id)
    if query:
        statement = statement.where(func.lower(User.full_name).contains(query.strip().lower()))
    if course is not None:
        statement = statement.where(Group.course == course)
    if group_id is not None:
        statement = statement.where(User.group_id == group_id)
    return list(db.scalars(statement.order_by(User.full_name).limit(limit)).unique().all())
