"""Схемы обращений: форма студента, «мои обращения», папки админки, адресаты."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedbackKindLiteral = Literal["dev", "methodist", "deanery", "unknown"]
FeedbackStatusLiteral = Literal["new", "in_progress", "answered", "archived"]


class FeedbackIn(BaseModel):
    kind: FeedbackKindLiteral = Field(description="Кому: разработчикам, методисту, в деканат или «не знаю»")
    text: str = Field(min_length=5, max_length=4000)
    group_id: int | None = None
    author_name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200, description="Email или телеграм для ответа")
    # Ловушка для ботов: в форме поле скрыто, человек его не заполнит.
    website: str | None = Field(default=None, max_length=200)


class ReplyOut(BaseModel):
    id: int
    author_kind: Literal["staff", "student"]
    # Для студента — от кого ответ («Деканат»), а не логин админа.
    author_title: str
    text: str
    created_at: datetime


class MyFeedbackOut(BaseModel):
    """Обращение глазами студента: без заметок и служебных полей."""

    id: int
    kind: FeedbackKindLiteral
    kind_title: str
    text: str
    status: FeedbackStatusLiteral
    created_at: datetime
    replies: list[ReplyOut]


class AdminReplyOut(ReplyOut):
    author_name: str | None


class AdminFeedbackOut(BaseModel):
    id: int
    kind: FeedbackKindLiteral
    kind_title: str
    recipient_title: str | None
    text: str
    status: FeedbackStatusLiteral
    group_id: int | None
    group_name: str | None
    author_name: str | None
    contact: str | None
    contact_is_email: bool
    admin_note: str | None
    created_at: datetime
    replies: list[AdminReplyOut]


class FolderCountOut(BaseModel):
    kind: FeedbackKindLiteral
    title: str
    total: int
    new: int


class FeedbackUpdateIn(BaseModel):
    status: FeedbackStatusLiteral | None = None
    kind: FeedbackKindLiteral | None = Field(default=None, description="Перенести в другую папку")
    admin_note: str | None = Field(default=None, max_length=1000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class RecipientOut(BaseModel):
    id: int
    kind: Literal["dev", "methodist", "deanery"]
    title: str
    emails: list[str]
    is_active: bool


class RecipientUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    emails: list[str] | None = Field(default=None, max_length=10)
    is_active: bool | None = None


class FeedbackCreatedOut(BaseModel):
    id: int
    kind_title: str
