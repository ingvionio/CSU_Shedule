"""Ввод и ответы API сессии и пересдач."""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

ExamKind = Literal["session", "retake"]
ExamType = Literal["consultation", "exam", "credit", "graded_credit", "other"]
ExamChangedField = Literal["date", "start_time", "room"]


class ExamWarningOut(BaseModel):
    sheet: str
    row: int
    column: str
    text: str
    reason: str


class ExamGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    course: int


class ExamFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ExamKind
    event_type: ExamType | None = None
    date: dt.date
    start_time: dt.time | None = None
    subject: str = Field(min_length=1, max_length=300)
    teacher: str | None = Field(default=None, max_length=200)
    room: str | None = Field(default=None, max_length=200)
    note: str | None = None

    @field_validator("subject", "teacher", "room", "note", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("start_time")
    @classmethod
    def local_time(cls, value: dt.time | None) -> dt.time | None:
        if value and value.tzinfo is not None:
            raise ValueError("Время должно быть местным, без часового пояса")
        return value


class ExamCreate(ExamFields):
    group_ids: list[int] = Field(min_length=1)


class ExamPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ExamKind | None = None
    event_type: ExamType | None = None
    date: dt.date | None = None
    start_time: dt.time | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    teacher: str | None = Field(default=None, max_length=200)
    room: str | None = Field(default=None, max_length=200)
    note: str | None = None
    group_ids: list[int] | None = Field(default=None, min_length=1)

    @field_validator("kind", "date", "subject", "group_ids")
    @classmethod
    def required_if_present(cls, value: object) -> object:
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value

    normalize_text = field_validator("subject", "teacher", "room", "note", mode="before")(ExamFields.normalize_text.__func__)
    local_time = field_validator("start_time")(ExamFields.local_time.__func__)


class ExamEventOut(ExamFields):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    groups: list[ExamGroupOut]
    cancelled: bool
    original: dict[ExamChangedField, str | None] | None
    source: Literal["import", "manual"]
    import_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_serializer("start_time")
    def format_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ExamMappingOut(BaseModel):
    short_name: str
    group_id: int | None
    group_name: str | None


class ExamPreviewRow(ExamFields):
    sheet: str
    row: int
    groups: list[ExamGroupOut]
    original: dict[ExamChangedField, str | None] | None

    @field_serializer("start_time")
    def format_time(self, value: dt.time | None) -> str | None:
        return value.strftime("%H:%M") if value else None


class ExamSheetOut(BaseModel):
    sheet: str
    groups: list[str]
    academic_year: str | None
    events_count: int


class ExamImportOut(BaseModel):
    events_count: int
    warnings: list[ExamWarningOut]
    mappings: list[ExamMappingOut]
    rows: list[ExamPreviewRow]
    sheets: list[ExamSheetOut]
    applied: bool = False
    import_id: int | None = None


class ExamImportHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    kind: ExamKind
    file_name: str
    events_count: int
    warnings: list[ExamWarningOut]
    uploaded_by: str | None
    uploaded_at: dt.datetime
