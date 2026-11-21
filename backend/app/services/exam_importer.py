"""Сопоставление групп и атомарная замена загруженных событий."""
from dataclasses import asdict
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Group, Semester
from app.models.exam import ExamEvent, ExamImport, exam_event_groups
from app.schemas.exam import ExamImportOut, ExamKind, ExamMappingOut, ExamPreviewRow
from app.services.exam_parser import ExamRow, ExamWarning, parse_workbook
from app.services.session_grid_parser import parse_workbook as parse_session_grid


def normalize_group(value: str) -> str:
    return re.sub(r"[\s\-–—−]", "", value).casefold()


def _match_group(name: str, groups: dict[str, Group]) -> Group | None:
    normalized = normalize_group(name)
    if normalized in groups:
        return groups[normalized]
    match = re.fullmatch(r"(.+?)([1-6])0(\d)", normalized)
    if match:
        direction, course, number = match.groups()
        return groups.get(normalize_group(f"ИТ{course}-{direction}б-{course}{number}"))
    return None


def _insert_events(db: Session, records: list[tuple[ExamRow, list[Group]]], semester_id: int,
                   kind: ExamKind, import_id: int) -> None:
    for row, groups in records:
        values = {key: getattr(row, key) for key in ["date", "start_time", "subject", "teacher", "room", "note",
                                                  "original", "event_type"]}
        db.add(ExamEvent(semester_id=semester_id, kind=kind, source="import", import_id=import_id,
                         groups=groups, **values))
    db.flush()


def import_workbook(db: Session, payload: bytes, semester: Semester, kind: ExamKind,
                    file_name: str, uploaded_by: str, *, apply: bool = False) -> ExamImportOut:
    if kind not in ("session", "retake"):
        raise ValueError("Неизвестный вид расписания")
    parsed = parse_session_grid(payload, semester.start_date) if kind == "session" else parse_workbook(payload)
    group_lookup = {normalize_group(group.name): group for group in db.scalars(select(Group).order_by(Group.id))}
    mappings: dict[str, ExamMappingOut] = {}
    records: list[tuple[ExamRow, list[Group]]] = []
    for row in parsed.rows:
        found: dict[int, Group] = {}
        for name in row.groups:
            group = _match_group(name, group_lookup)
            mappings.setdefault(name, ExamMappingOut(short_name=name, group_id=group.id if group else None,
                                                     group_name=group.name if group else None))
            if group:
                found[group.id] = group
            else:
                parsed.warnings.append(ExamWarning(row.sheet, row.row, row.group_column, name,
                                                   f"группа не найдена: {name}"))
        if found:
            records.append((row, list(found.values())))
        elif not row.groups:
            parsed.warnings.append(ExamWarning(row.sheet, row.row, row.group_column, "", "не разобрано: нет групп"))
    report = ExamImportOut(
        events_count=len(records), warnings=[asdict(issue) for issue in parsed.warnings],
        mappings=list(mappings.values()),
        sheets=[asdict(sheet) for sheet in parsed.sheets],
        rows=[ExamPreviewRow(kind=kind, groups=groups, **{key: value for key, value in asdict(row).items()
                             if key not in ("groups", "group_column")}) for row, groups in records],
    )
    if not apply:
        return report
    try:
        old_ids = select(ExamEvent.id).where(ExamEvent.semester_id == semester.id, ExamEvent.kind == kind,
                                           ExamEvent.source == "import")
        db.execute(delete(exam_event_groups).where(exam_event_groups.c.event_id.in_(old_ids)))
        db.execute(delete(ExamEvent).where(ExamEvent.id.in_(old_ids)), execution_options={"synchronize_session": "fetch"})
        record = ExamImport(semester_id=semester.id, kind=kind, file_name=file_name, events_count=len(records),
                            warnings=[asdict(issue) for issue in parsed.warnings], uploaded_by=uploaded_by)
        db.add(record)
        db.flush()
        _insert_events(db, records, semester.id, kind, record.id)
        report.import_id = record.id
        db.commit()
        report.applied = True
    except Exception:
        db.rollback()
        raise
    return report
