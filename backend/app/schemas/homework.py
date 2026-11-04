from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

HomeworkSource = Literal["from_class", "moodle", "chat", "unknown"]
HomeworkStatus = Literal["published", "completed", "archived"]


class HomeworkIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=5000)
    lesson_date: date | None = None
    lesson_id: int | None = None
    subject: str | None = Field(default=None, max_length=300)
    due_date: date | None = None
    source: HomeworkSource = "from_class"


class HomeworkPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=5000)
    lesson_date: date | None = None
    lesson_id: int | None = None
    subject: str | None = Field(default=None, max_length=300)
    due_date: date | None = None
    source: HomeworkSource | None = None
    status: HomeworkStatus | None = None
    version: int = Field(ge=1)


class HomeworkOut(BaseModel):
    id: int
    group_id: int
    group_name: str
    lesson_id: int | None
    lesson_date: date | None
    subject: str | None
    title: str
    body: str
    due_date: date | None
    source: HomeworkSource
    status: HomeworkStatus
    version: int
    created_by: int
    created_by_name: str
    updated_by: int
    updated_by_name: str
    created_at: datetime
    updated_at: datetime
    completed_by_me: bool


class HomeworkListOut(BaseModel):
    can_edit: bool
    items: list[HomeworkOut]


class EditorOut(BaseModel):
    user_id: int
    full_name: str
    group_id: int
    is_primary: bool
    active: bool


class EditorIn(BaseModel):
    user_id: int
    is_primary: bool = False
