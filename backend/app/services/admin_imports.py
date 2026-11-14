"""Проверка загрузок и отчёты; правила записи остаются в импортёрах."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Group, GroupHomework, Lesson, LessonOverride, ScheduleImport, Semester
from app.schemas.imports import (
    ImportHistoryOut, ImportIssueOut, SemesterGroupOut, SemesterImportOut, WeeklyFileOut, WeeklyImportOut,
)
from app.services.excel_parser import parse_workbook
from app.services.importer import import_workbook
from app.services.weeks import parity_of_week
from app.services.schedule import ScheduleError, active_semester
from app.services.weekly_importer import import_weekly

if TYPE_CHECKING:
    from fastapi import UploadFile

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _save_uploads(files: list[UploadFile], temporary: Path, extensions: set[str]) -> list[tuple[str, str]]:
    if not files:
        raise UploadError("Выберите хотя бы один файл расписания")
    sources: list[tuple[str, str]] = []
    total = 0
    for index, upload in enumerate(files):
        name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(name).suffix.lower()
        if extension not in extensions:
            raise UploadError(f"Недопустимый формат файла «{name}». Ожидается: {', '.join(sorted(extensions))}")
        path = temporary / f"{index}{extension}"
        size = 0
        with path.open("wb") as target:
            while chunk := upload.file.read(READ_CHUNK_BYTES):
                size += len(chunk)
                total += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise UploadError(f"Файл «{name}» превышает допустимый размер (20 МБ)", 413)
                if total > MAX_TOTAL_BYTES:
                    raise UploadError("Суммарный размер файлов превышает 50 МБ", 413)
                target.write(chunk)
        sources.append((str(path), name))
    return sources


def _semester(db: Session) -> Semester:
    try:
        return active_semester(db)
    except ScheduleError as error:
        raise UploadError(str(error), 409) from error


def upload_weekly(
    db: Session, files: list[UploadFile], dry_run: bool, skip_errors: bool, admin: str,
) -> WeeklyImportOut:
    semester = _semester(db)
    try:
        with TemporaryDirectory(prefix="schedule-upload-") as temporary:
            sources = _save_uploads(files, Path(temporary), {".xlsx", ".zip"})
            report = import_weekly(db, sources, semester, skip_errors=skip_errors, uploaded_by=admin)
        result = WeeklyImportOut(
            files=[WeeklyFileOut(
                file_name=file.file_name, group_name=file.parsed.group_name, week_number=file.parsed.week_number,
                parity=(parity_of_week(semester, file.parsed.week_number)
                        if file.parsed.week_number is not None
                        and 1 <= file.parsed.week_number <= semester.total_weeks else None),
                start_date=file.parsed.start_date, end_date=file.parsed.end_date,
                lessons_count=len(file.parsed.lessons), errors=[asdict(issue) for issue in file.parsed.errors],
                warnings=[asdict(issue) for issue in file.parsed.warnings],
            ) for file in report.files],
            files_count=len(report.files), groups_count=report.groups_count, groups_created=report.groups_created,
            lessons_created=report.lessons_created, overrides_deleted=report.overrides_deleted,
            homework_rebound=report.homework_rebound, homework_unbound=report.homework_unbound,
            errors_count=len(report.errors), warnings_count=len(report.warnings),
            applied=not dry_run and report.import_id is not None,
            import_id=report.import_id if not dry_run else None,
        )
        if result.applied:
            db.commit()
        else:
            db.rollback()
        return result
    except Exception:
        db.rollback()
        raise


def upload_semester(db: Session, files: list[UploadFile], dry_run: bool, admin: str) -> SemesterImportOut:
    semester = _semester(db)
    with TemporaryDirectory(prefix="schedule-upload-") as temporary:
        [(path, name)] = _save_uploads(files, Path(temporary), {".xlsx"})
        result = SemesterImportOut(file_name=name, semester_title=semester.title)
        # Повреждённая книга — результат проверки, а не ошибка сервера.
        try:
            parsed = parse_workbook(path)
        except Exception:
            result.errors = [ImportIssueOut(reason="Не удалось прочитать книгу Excel")]
            return result

        group_names = list(dict.fromkeys(group.name for group in parsed.groups))
        lesson_counts = Counter(lesson.group_name for lesson in parsed.lessons)
        result.groups = [SemesterGroupOut(name=name, lessons_count=lesson_counts[name]) for name in group_names]
        result.warnings = [ImportIssueOut(**asdict(issue)) for issue in parsed.errors]
        old_ids = select(Lesson.id).join(Group, Lesson.group_id == Group.id).where(
            Lesson.semester_id == semester.id, Group.name.in_(group_names))
        result.lessons_replaced = db.scalar(select(func.count()).select_from(old_ids.subquery()))
        result.overrides_deleted = db.scalar(select(func.count()).select_from(LessonOverride).where(
            LessonOverride.lesson_id.in_(old_ids)))
        if dry_run:
            result.homework_affected = db.scalar(select(func.count()).select_from(GroupHomework).join(
                Lesson, GroupHomework.lesson_id == Lesson.id,
            ).where(Lesson.id.in_(old_ids), GroupHomework.group_id == Lesson.group_id))
        existing_groups = db.scalar(select(func.count()).select_from(Group).where(Group.name.in_(group_names)))
        result.groups_created = len(group_names) - existing_groups
        result.lessons_created = len(parsed.lessons)
        if not dry_run:
            report = import_workbook(db, path, semester, file_name=name, uploaded_by=admin)
            result.import_id = report.import_id
            result.groups_created = report.groups_created
            result.lessons_created = report.lessons_created
            result.homework_rebound = report.homework_rebound
            result.homework_unbound = report.homework_unbound
            result.applied = True
        return result


def import_history(db: Session, limit: int) -> list[ImportHistoryOut]:
    records = db.scalars(select(ScheduleImport).order_by(
        ScheduleImport.uploaded_at.desc(), ScheduleImport.id.desc()).limit(limit))
    return [ImportHistoryOut(
        id=record.id, file_name=record.file_name, uploaded_at=record.uploaded_at, uploaded_by=record.uploaded_by,
        status=record.status, lessons_count=record.lessons_count,
        errors_count=sum(issue.get("severity") == "error" for issue in record.errors or []),
        warnings_count=sum(issue.get("severity") != "error" for issue in record.errors or []),
    ) for record in records]
