from datetime import date, datetime

from pydantic import BaseModel, Field


class ImportIssueOut(BaseModel):
    sheet: str = ""
    cell: str = ""
    text: str = ""
    reason: str


class WeeklyFileOut(BaseModel):
    file_name: str
    group_name: str | None
    week_number: int | None
    start_date: date | None
    end_date: date | None
    lessons_count: int
    errors: list[ImportIssueOut]
    warnings: list[ImportIssueOut]


class WeeklyImportOut(BaseModel):
    files: list[WeeklyFileOut]
    files_count: int
    groups_count: int
    groups_created: int
    lessons_created: int
    overrides_deleted: int
    errors_count: int
    warnings_count: int
    applied: bool
    import_id: int | None = None


class SemesterGroupOut(BaseModel):
    name: str
    lessons_count: int


class SemesterImportOut(BaseModel):
    file_name: str
    groups: list[SemesterGroupOut] = Field(default_factory=list)
    errors: list[ImportIssueOut] = Field(default_factory=list)
    warnings: list[ImportIssueOut] = Field(default_factory=list)
    lessons_replaced: int = 0
    overrides_deleted: int = 0
    groups_created: int = 0
    lessons_created: int = 0
    semester_title: str
    applied: bool = False
    import_id: int | None = None


class ImportHistoryOut(BaseModel):
    id: int
    file_name: str
    uploaded_at: datetime
    uploaded_by: str | None
    status: str
    lessons_count: int
    errors_count: int
    warnings_count: int
