"""Pydantic-схемы контракта бэкенд -> фронтенд (см. 03-schedule-json.md)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LessonStatusLiteral = Literal["regular", "changed", "cancelled", "moved_out", "moved_in", "added"]
ParityLiteral = Literal["odd", "even"]


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    course: int
    direction: str | None = None


class DirectionOut(BaseModel):
    code: str
    courses: list[int] = Field(description="Курсы, на которых есть группы этого направления")


class TimeSlotOut(BaseModel):
    """Сетка звонков: номер пары и её время."""

    number: int
    start_time: str
    end_time: str


class LessonTypeOut(BaseModel):
    code: str
    name: str


class ChangeOut(BaseModel):
    """Детали временного изменения."""

    override_id: int = Field(description="id изменения — чтобы админ мог его откатить")
    kind: Literal["cancel", "replace", "move", "add"]
    comment: str | None = None
    original: dict | None = None
    moved_to: dict | None = None
    moved_from: dict | None = None


class LessonOut(BaseModel):
    id: str
    start_time: str = Field(description="HH:MM, заполнено всегда")
    end_time: str
    slot: int | None = Field(default=None, description="Номер в сетке звонков; null -- пара вне сетки")
    subject: str
    type: LessonTypeOut
    room: str | None = None
    teacher: str | None = None
    subgroup: int | None = Field(default=None, description="Подгруппа из Excel; null -- вся группа")
    status: LessonStatusLiteral = "regular"
    change: ChangeOut | None = None


class DayOut(BaseModel):
    date: date
    weekday: int = Field(description="1 = пн ... 6 = сб")
    is_today: bool
    lessons: list[LessonOut]


class WeekOut(BaseModel):
    number: int
    parity: ParityLiteral
    start_date: date
    end_date: date
    is_current: bool
    prev: int | None = None
    next: int | None = None


class SemesterOut(BaseModel):
    id: int
    title: str
    total_weeks: int


class WeekScheduleOut(BaseModel):
    """Ответ GET /groups/{group_id}/schedule?week=N."""

    group: GroupOut
    week: WeekOut
    generated_at: datetime
    days: list[DayOut]


class CurrentWeekOut(BaseModel):
    """Ответ GET /weeks/current."""

    number: int
    parity: ParityLiteral
    start_date: date
    end_date: date
    semester: SemesterOut
