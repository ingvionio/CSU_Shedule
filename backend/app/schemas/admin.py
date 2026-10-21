"""Схемы админского API: вход и временные изменения расписания."""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OverrideKindLiteral = Literal["cancel", "move", "replace", "add"]
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class LoginIn(BaseModel):
    login: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class OverrideIn(BaseModel):
    """Временное изменение для одной группы или потока.

    Поля итоговой пары (время, предмет, формат, преподаватель, аудитория):
    `null` — оставить как у исходной пары. Значение, совпадающее с исходной
    парой, тоже считается «без изменений» — так при изменении для потока у
    каждой группы сохраняются свои преподаватель и аудитория. Пустая строка в
    `teacher` / `room` — убрать значение.
    """

    group_ids: list[int] = Field(min_length=1, max_length=32)
    kind: OverrideKindLiteral
    date: dt.date = Field(description="Дата исходной пары; для add — дата новой пары")
    source_lesson_id: int | None = Field(default=None, description="id постоянной пары (без префикса l-)")
    target_date: dt.date | None = Field(default=None, description="Для move: новая дата")

    slot: int | None = Field(default=None, ge=1, le=8, description="Номер пары: время подставится из сетки")
    start_time: str | None = Field(default=None, pattern=TIME_PATTERN, description="Своё время, HH:MM")
    end_time: str | None = Field(default=None, pattern=TIME_PATTERN)

    subject: str | None = Field(default=None, max_length=300)
    lesson_type: str | None = Field(default=None, description="Код формата из /lesson-types")
    teacher: str | None = Field(default=None, max_length=200)
    room: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


class OverrideCreatedOut(BaseModel):
    batch_id: str
    override_ids: list[int]
    group_ids: list[int]


class OverrideDeletedOut(BaseModel):
    deleted: int


class CatalogOut(BaseModel):
    """Справочники для подсказок в форме изменения."""

    subjects: list[str]
    teachers: list[str]
    rooms: list[str]
