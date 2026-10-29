"""Схемы рассылки: сообщения методиста, инбокс студента, прочтения."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ImportanceLiteral = Literal["low", "normal", "high"]
TargetTypeLiteral = Literal["all", "course", "direction", "group", "students"]


class TargetIn(BaseModel):
    """Кому: все, курсы, потоки (направление, при желании на отдельных курсах), группы или студенты."""

    type: TargetTypeLiteral
    courses: list[int] = Field(default_factory=list, max_length=6)
    directions: list[str] = Field(default_factory=list, max_length=20)
    group_ids: list[int] = Field(default_factory=list, max_length=200)
    user_ids: list[int] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def _check_lists(self) -> TargetIn:
        required = {"course": self.courses, "direction": self.directions, "group": self.group_ids, "students": self.user_ids}
        if self.type in required and not required[self.type]:
            raise ValueError(f"для адресации «{self.type}» нужен хотя бы один адресат")
        return self


class MessageIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    importance: ImportanceLiteral = "normal"
    target: TargetIn


class InboxMessageOut(BaseModel):
    id: int
    title: str
    body: str
    importance: ImportanceLiteral
    sent_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None
    requires_ack: bool
    # Непрочитано, а для важных — не подтверждено.
    is_unread: bool


class InboxOut(BaseModel):
    unread_count: int
    messages: list[InboxMessageOut]


class AdminMessageOut(BaseModel):
    id: int
    title: str
    body: str
    importance: ImportanceLiteral
    target: dict
    target_title: str
    created_by: str | None
    sent_at: datetime
    last_reminded_at: datetime | None
    recipients_total: int
    read_count: int
    acknowledged_count: int


class RecipientStatusOut(BaseModel):
    user_id: int
    full_name: str
    group_name: str | None
    read_at: datetime | None
    acknowledged_at: datetime | None
    reminded_at: datetime | None


class AdminMessageDetailOut(AdminMessageOut):
    recipients: list[RecipientStatusOut]


class RemindOut(BaseModel):
    reminded: int


class StudentOut(BaseModel):
    id: int
    full_name: str
    group_id: int | None
    group_name: str | None
    course: int | None
