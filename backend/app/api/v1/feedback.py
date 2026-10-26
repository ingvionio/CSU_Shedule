"""Обращения студентов: публичная часть и папки в админке."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin
from app.models import FeedbackMessage, FeedbackRecipient, FeedbackReply
from app.schemas.feedback import (
    AdminFeedbackOut,
    AdminReplyOut,
    FeedbackCreatedOut,
    FeedbackIn,
    FeedbackStatusLiteral,
    FeedbackKindLiteral,
    FeedbackUpdateIn,
    FolderCountOut,
    MyFeedbackOut,
    RecipientOut,
    RecipientUpdateIn,
    ReplyIn,
    ReplyOut,
)
from app.services import feedback as feedback_service
from app.services.feedback import KIND_TITLES
from app.services.mailer import deliver_by_ids

router = APIRouter()
admin_router = APIRouter(prefix="/admin/feedback", dependencies=[Depends(require_admin)])

# Случайный токен устройства, по нему студент без входа видит свои обращения.
TokenHeader = Header(default=None, alias="X-Feedback-Token", min_length=16, max_length=128)


def _reply_title(message: FeedbackMessage, reply: FeedbackReply) -> str:
    return KIND_TITLES[message.kind] if reply.author_kind == "staff" else "Вы"


def _my_out(message: FeedbackMessage) -> MyFeedbackOut:
    return MyFeedbackOut(
        id=message.id,
        kind=message.kind,
        kind_title=KIND_TITLES[message.kind],
        text=message.text,
        status=message.status,
        created_at=message.created_at,
        replies=[
            ReplyOut(
                id=reply.id,
                author_kind=reply.author_kind,
                author_title=_reply_title(message, reply),
                text=reply.text,
                created_at=reply.created_at,
            )
            for reply in message.replies
        ],
    )


def _admin_out(message: FeedbackMessage) -> AdminFeedbackOut:
    return AdminFeedbackOut(
        id=message.id,
        kind=message.kind,
        kind_title=KIND_TITLES[message.kind],
        recipient_title=message.recipient.title if message.recipient else None,
        text=message.text,
        status=message.status,
        group_id=message.group_id,
        group_name=message.group.name if message.group else None,
        author_name=message.author_name,
        contact=message.contact,
        contact_is_email=feedback_service.is_email(message.contact),
        admin_note=message.admin_note,
        created_at=message.created_at,
        replies=[
            AdminReplyOut(
                id=reply.id,
                author_kind=reply.author_kind,
                author_title=_reply_title(message, reply),
                author_name=reply.author_name,
                text=reply.text,
                created_at=reply.created_at,
            )
            for reply in message.replies
        ],
    )


def _recipient_out(recipient: FeedbackRecipient) -> RecipientOut:
    return RecipientOut(
        id=recipient.id,
        kind=recipient.kind,
        title=recipient.title,
        emails=list(recipient.emails or []),
        is_active=recipient.is_active,
    )


def _raise(error: feedback_service.FeedbackError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


# --- студент ---


@router.post(
    "/feedback",
    response_model=FeedbackCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Отправить обращение",
)
def create_feedback(
    data: FeedbackIn,
    request: Request,
    background: BackgroundTasks,
    token: str | None = TokenHeader,
    db: Session = Depends(get_db),
) -> FeedbackCreatedOut:
    try:
        message, outbox_ids = feedback_service.create_message(
            db, data, token, request.client.host if request.client else None
        )
    except feedback_service.FeedbackError as error:
        raise _raise(error) from error

    background.add_task(deliver_by_ids, outbox_ids)
    return FeedbackCreatedOut(id=message.id, kind_title=KIND_TITLES[message.kind])


@router.get("/feedback/mine", response_model=list[MyFeedbackOut], summary="Мои обращения и ответы на них")
def my_feedback(token: str | None = TokenHeader, db: Session = Depends(get_db)) -> list[MyFeedbackOut]:
    if not token:
        return []
    return [_my_out(message) for message in feedback_service.list_for_token(db, token)]


# --- админка ---


@admin_router.get("", response_model=list[AdminFeedbackOut], summary="Обращения в папке")
def admin_feedback(
    kind: FeedbackKindLiteral | None = Query(default=None, description="Папка"),
    status_: FeedbackStatusLiteral | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[AdminFeedbackOut]:
    return [_admin_out(message) for message in feedback_service.admin_list(db, kind, status_)]


@admin_router.get("/folders", response_model=list[FolderCountOut], summary="Папки и число новых обращений")
def feedback_folders(db: Session = Depends(get_db)) -> list[FolderCountOut]:
    summary = feedback_service.folder_summary(db)
    return [
        FolderCountOut(kind=kind, title=title, total=summary[kind]["total"], new=summary[kind]["new"])
        for kind, title in KIND_TITLES.items()
    ]


@admin_router.get("/recipients", response_model=list[RecipientOut], summary="Адресаты и их почта")
def feedback_recipients(db: Session = Depends(get_db)) -> list[RecipientOut]:
    return [_recipient_out(item) for item in feedback_service.list_recipients(db)]


@admin_router.patch("/recipients/{recipient_id}", response_model=RecipientOut, summary="Изменить адресата")
def update_recipient(recipient_id: int, data: RecipientUpdateIn, db: Session = Depends(get_db)) -> RecipientOut:
    try:
        return _recipient_out(feedback_service.update_recipient(db, recipient_id, data))
    except feedback_service.FeedbackError as error:
        raise _raise(error) from error


@admin_router.patch("/{message_id}", response_model=AdminFeedbackOut, summary="Статус, заметка, перенос в папку")
def update_feedback(
    message_id: int,
    data: FeedbackUpdateIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AdminFeedbackOut:
    try:
        message, outbox_ids = feedback_service.update_message(db, message_id, data)
    except feedback_service.FeedbackError as error:
        raise _raise(error) from error
    background.add_task(deliver_by_ids, outbox_ids)
    return _admin_out(message)


@admin_router.post(
    "/{message_id}/replies",
    response_model=AdminFeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ответить студенту",
)
def reply_feedback(
    message_id: int,
    data: ReplyIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> AdminFeedbackOut:
    try:
        message, outbox_ids = feedback_service.add_reply(db, message_id, data.text, admin)
    except feedback_service.FeedbackError as error:
        raise _raise(error) from error
    background.add_task(deliver_by_ids, outbox_ids)
    return _admin_out(message)
