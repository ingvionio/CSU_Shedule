"""Схемы обращений: форма студента, «мои обращения», папки админки, адресаты."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

QuestionKindLiteral = Literal["dev", "methodist", "deanery", "unknown"]
FeedbackKindLiteral = Literal[QuestionKindLiteral, "certificate"]
FeedbackStatusLiteral = Literal["new", "in_progress", "answered", "archived"]


def _check_controls(value: str | None, *, multiline: bool) -> str | None:
    allowed = "\n\r\t" if multiline else ""
    if value is not None and any(
        (ord(char) < 32 or 127 <= ord(char) <= 159) and char not in allowed for char in value
    ):
        raise ValueError("Недопустимые управляющие символы")
    return value


class FeedbackFormIn(BaseModel):
    # Ловушка для ботов: в форме поле скрыто, человек его не заполнит.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("website")
    @classmethod
    def check_website(cls, value: str | None) -> str | None:
        return _check_controls(value, multiline=False)


class FeedbackIn(FeedbackFormIn):
    kind: QuestionKindLiteral = Field(description="Кому: разработчикам, методисту, в деканат или «не знаю»")
    text: str = Field(min_length=5, max_length=4000)
    group_id: int | None = None
    author_name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=200, description="Email или телеграм для ответа")

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        _check_controls(value, multiline=True)
        text = value.strip()
        if len(text) < 5:
            raise ValueError("Обращение должно содержать хотя бы 5 символов")
        return text

    @field_validator("contact", "author_name")
    @classmethod
    def check_single_line(cls, value: str | None) -> str | None:
        return _check_controls(value, multiline=False)


class CertificateRequestIn(FeedbackFormIn):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["certificate"]
    purpose: str = Field(max_length=4000)
    copies: int = Field(strict=True, ge=1, le=2_147_483_647)
    text: str = Field(default="", max_length=4000)

    @field_validator("purpose")
    @classmethod
    def check_purpose(cls, value: str) -> str:
        _check_controls(value, multiline=False)
        purpose = value.strip()
        if not purpose:
            raise ValueError("Укажите, для чего нужна справка")
        return purpose

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        _check_controls(value, multiline=True)
        return value.strip()


FeedbackSubmission = Annotated[FeedbackIn | CertificateRequestIn, Field(discriminator="kind")]


class ReplyOut(BaseModel):
    id: int
    author_kind: Literal["staff", "student"]
    # Для студента — от кого ответ («Деканат»), а не логин админа.
    author_title: str
    text: str
    created_at: datetime


class CertificateDetailsOut(BaseModel):
    purpose: str | None
    copies: int | None


class MyFeedbackOut(CertificateDetailsOut):
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


class AdminFeedbackOut(CertificateDetailsOut):
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
    kind: QuestionKindLiteral | None = Field(default=None, description="Перенести в другую папку")
    admin_note: str | None = Field(default=None, max_length=1000)

    @field_validator("admin_note")
    @classmethod
    def check_note(cls, value: str | None) -> str | None:
        return _check_controls(value, multiline=True)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def check_reply(cls, value: str) -> str:
        _check_controls(value, multiline=True)
        if not value.strip():
            raise ValueError("Введите текст ответа")
        return value


class RecipientOut(BaseModel):
    id: int
    kind: Literal["dev", "methodist", "deanery"]
    title: str
    emails: list[str]
    is_active: bool


class RecipientUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    emails: list[Annotated[str, StringConstraints(max_length=200)]] | None = Field(default=None, max_length=10)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str | None) -> str | None:
        return _check_controls(value, multiline=False)


class FeedbackCreatedOut(BaseModel):
    id: int
    kind_title: str
