"""Рассылка: инбокс студента (/me/messages) и раздел методиста (/admin/messages)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import current_student
from app.core.db import get_db
from app.core.security import require_admin
from app.models import Message, MessageRecipient, User
from app.schemas.message import (
    AdminMessageDetailOut,
    AdminMessageOut,
    InboxMessageOut,
    InboxOut,
    MessageIn,
    RecipientStatusOut,
    RemindOut,
    StudentOut,
)
from app.services import messages as messages_service
from app.services import push as push_service

router = APIRouter(prefix="/me/messages")
admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _raise(error: messages_service.MessageError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


def _inbox_out(recipient: MessageRecipient) -> InboxMessageOut:
    message = recipient.message
    return InboxMessageOut(
        id=message.id,
        title=message.title,
        body=message.body,
        importance=message.importance,
        sent_at=message.sent_at,
        read_at=recipient.read_at,
        acknowledged_at=recipient.acknowledged_at,
        requires_ack=messages_service.requires_ack(message),
        is_unread=messages_service.is_unread(message, recipient),
    )


async def _admin_out(db: AsyncSession, message: Message, total: int, read: int, acknowledged: int) -> AdminMessageOut:
    return AdminMessageOut(
        id=message.id,
        title=message.title,
        body=message.body,
        importance=message.importance,
        target=message.target,
        target_title=await messages_service.target_title(db, message.target),
        created_by=message.created_by,
        sent_at=message.sent_at,
        last_reminded_at=message.last_reminded_at,
        recipients_total=total,
        read_count=read,
        acknowledged_count=acknowledged,
    )


# --- студент ---


@router.get("", response_model=InboxOut, summary="Мои сообщения")
async def my_messages(user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")) -> InboxOut:
    return InboxOut(
        unread_count=await messages_service.unread_count(db, user.id),
        messages=[_inbox_out(item) for item in await messages_service.inbox(db, user.id)],
    )


@router.get("/{message_id}", response_model=InboxMessageOut, summary="Открыть сообщение (отмечает прочитанным)")
async def open_message(message_id: int, user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")) -> InboxMessageOut:
    try:
        return _inbox_out(await messages_service.open_message(db, user.id, message_id))
    except messages_service.MessageError as error:
        raise _raise(error) from error


@router.post("/{message_id}/acknowledge", response_model=InboxMessageOut, summary="«Ознакомлен» для важного сообщения")
async def acknowledge(message_id: int, user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")) -> InboxMessageOut:
    try:
        return _inbox_out(await messages_service.acknowledge(db, user.id, message_id))
    except messages_service.MessageError as error:
        raise _raise(error) from error


# --- методист ---


@admin_router.get("/users", response_model=list[StudentOut], summary="Студенты с профилем — для адресации")
async def students(
    q: str | None = Query(default=None, max_length=100, description="Часть ФИО"),
    course: int | None = Query(default=None, ge=1, le=6),
    group_id: int | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[StudentOut]:
    return [
        StudentOut(
            id=user.id,
            full_name=user.full_name,
            group_id=user.group_id,
            group_name=user.group.name if user.group else None,
            course=user.group.course if user.group else None,
        )
        for user in await messages_service.list_students(db, q, course, group_id)
    ]


@admin_router.post(
    "/messages", response_model=AdminMessageOut, status_code=status.HTTP_201_CREATED, summary="Отправить сообщение"
)
async def create_message(
    data: MessageIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db, scope="function"),
    admin: str = Depends(require_admin),
) -> AdminMessageOut:
    try:
        message, push_to = await messages_service.create_message(db, data, admin)
    except messages_service.MessageError as error:
        raise _raise(error) from error

    background.add_task(push_service.notify_message, message.id, push_to, reminder=False)
    counts = await messages_service.counts(db, message.id)
    return await _admin_out(db, message, *counts)


@admin_router.get("/messages", response_model=list[AdminMessageOut], summary="Сообщения и прогресс прочтения")
async def admin_messages(db: AsyncSession = Depends(get_db, scope="function")) -> list[AdminMessageOut]:
    rows = await messages_service.admin_list(db)
    return [await _admin_out(db, *row) for row in rows]


@admin_router.get("/messages/{message_id}", response_model=AdminMessageDetailOut, summary="Получатели и их статусы")
async def admin_message(message_id: int, db: AsyncSession = Depends(get_db, scope="function")) -> AdminMessageDetailOut:
    try:
        message, recipients = await messages_service.admin_detail(db, message_id)
    except messages_service.MessageError as error:
        raise _raise(error) from error

    counts = await messages_service.counts(db, message.id)
    summary = await _admin_out(db, message, *counts)
    return AdminMessageDetailOut(
        **summary.model_dump(),
        recipients=[
            RecipientStatusOut(
                user_id=recipient.user_id,
                full_name=recipient.user.full_name,
                group_name=group_name,
                read_at=recipient.read_at,
                acknowledged_at=recipient.acknowledged_at,
                reminded_at=recipient.reminded_at,
            )
            for recipient, group_name in recipients
        ],
    )


@admin_router.post("/messages/{message_id}/remind", response_model=RemindOut, summary="Напомнить непрочитавшим")
async def remind(message_id: int, background: BackgroundTasks, db: AsyncSession = Depends(get_db, scope="function")) -> RemindOut:
    try:
        user_ids = await messages_service.remind(db, message_id)
    except messages_service.MessageError as error:
        raise _raise(error) from error

    background.add_task(push_service.notify_message, message_id, user_ids, reminder=True)
    return RemindOut(reminded=len(user_ids))


@admin_router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить сообщение")
async def delete_message(message_id: int, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    try:
        await messages_service.delete_message(db, message_id)
    except messages_service.MessageError as error:
        raise _raise(error) from error
