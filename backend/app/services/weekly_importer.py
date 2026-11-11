"""Пакетная загрузка понедельных книг; транзакцией управляет вызывающий код."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Group, Lesson, LessonOverride, Room, ScheduleImport, Semester, Subject, Teacher, TimeSlot
from app.services import weeks
from app.services.groups import direction_of
from app.services.importer import DEFAULT_TIME_SLOTS, _get_or_create, _parse_time, ensure_reference_data
from app.services.weekly_parser import GROUP_RE, WeeklyIssue, WeeklyParseResult, parse_weekly_workbook


@dataclass
class WeeklyFileReport:
    file_name: str
    parsed: WeeklyParseResult
    times: list[tuple[time, time, int | None]] = field(default_factory=list)


@dataclass
class WeeklyImportReport:
    files: list[WeeklyFileReport] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    groups_created: int = 0
    groups_count: int = 0
    lessons_created: int = 0
    overrides_deleted: int = 0
    import_id: int | None = None


def _read_sources(paths: list[str | tuple[str, str]], temporary: Path) -> list[WeeklyFileReport]:
    files: list[WeeklyFileReport] = []

    def read(path: Path, name: str | None = None, fallback_name: str | None = None) -> None:
        try:
            parsed = parse_weekly_workbook(path, file_name=fallback_name)
        except Exception:
            failed(name or str(path), "Не удалось прочитать книгу Excel")
            return
        files.append(WeeklyFileReport(name or str(path), parsed))

    def failed(name: str, reason: str) -> None:
        files.append(WeeklyFileReport(name, WeeklyParseResult(errors=[WeeklyIssue("", "", "", reason)])))

    for source in paths:
        raw, display_name = source if isinstance(source, tuple) else (source, source)
        path = Path(raw)
        try:
            if path.is_dir():
                children = sorted(child for child in path.rglob("*") if child.is_file() and child.suffix.lower() == ".xlsx")
                if not children:
                    failed(raw, "В папке не найдены файлы .xlsx")
                for child in children:
                    read(child)
            elif path.suffix.lower() == ".zip":
                with ZipFile(path) as archive:
                    members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".xlsx")]
                    if not members:
                        failed(display_name, "В архиве не найдены файлы .xlsx")
                    for member in members:
                        member_name = member.filename.replace("\\", "/").rsplit("/", 1)[-1]
                        name = f"{display_name}!{member_name if isinstance(source, tuple) else member.filename}"
                        fallback_name = member.filename.replace("\\", "/").rsplit("/", 1)[-1]
                        if not member.flag_bits & 0x800 and not GROUP_RE.search(fallback_name):
                            for encoding in ("cp866", "cp1251"):
                                try:
                                    decoded = fallback_name.encode("cp437").decode(encoding)
                                except (UnicodeEncodeError, UnicodeDecodeError):
                                    continue
                                if GROUP_RE.search(decoded):
                                    fallback_name = decoded
                                    break
                        # Имена архива не используются как пути распаковки.
                        extracted = temporary / f"{len(files)}.xlsx"
                        try:
                            extracted.write_bytes(archive.read(member))
                            read(extracted, name, fallback_name)
                        except (OSError, ValueError, BadZipFile, RuntimeError, NotImplementedError) as error:
                            failed(name, f"Не удалось извлечь файл: {error}")
            elif path.suffix.lower() == ".xlsx":
                read(path, display_name, display_name if isinstance(source, tuple) else None)
            else:
                failed(display_name, "Ожидался файл .xlsx, папка или архив .zip")
        except (OSError, ValueError, BadZipFile) as error:
            failed(display_name, f"Не удалось прочитать путь: {error}")
    return files


def _resolve_times(parsed: WeeklyParseResult, slots: dict[int, TimeSlot]) -> list[tuple[time, time, int | None]]:
    resolved: list[tuple[time, time, int | None]] = []
    anchors: dict[int, tuple[int, int]] = {}
    anchor_date = date(2000, 1, 1)
    for lesson in parsed.lessons:
        if lesson.custom_start is not None:
            start = _parse_time(lesson.custom_start)
            anchor = min(slots.values(), key=lambda slot: (abs(
                (datetime.combine(anchor_date, slot.start_time) - datetime.combine(anchor_date, start)).total_seconds()
            ), slot.number))
            duration = datetime.combine(anchor_date, anchor.end_time) - datetime.combine(anchor_date, anchor.start_time)
            end = (datetime.combine(anchor_date, start) + duration).time()
            number = None
            anchors[lesson.weekday] = anchor.number, lesson.block_index
        else:
            number = lesson.slot_label
            if lesson.weekday in anchors:
                anchor_number, anchor_index = anchors[lesson.weekday]
                number = anchor_number + lesson.block_index - anchor_index
            if number not in slots:
                parsed.errors.append(WeeklyIssue(parsed.sheet, lesson.source_ref.split("!")[-1], lesson.source_text,
                                                 f"Нет пары {number} в сетке звонков"))
                continue
            start, end = slots[number].start_time, slots[number].end_time
        if end <= start:
            parsed.errors.append(WeeklyIssue(parsed.sheet, lesson.source_ref.split("!")[-1], lesson.source_text,
                                             "Конец пары должен быть позже начала"))
        resolved.append((start, end, number))
    return resolved


def import_weekly(
    session: Session,
    paths: list[str | tuple[str, str]],
    semester: Semester,
    skip_errors: bool = False,
    uploaded_by: str | None = None,
) -> WeeklyImportReport:
    report = WeeklyImportReport()
    with TemporaryDirectory(prefix="schedule-weekly-") as temporary:
        report.files = _read_sources(paths, Path(temporary))

    # Проверяем все книги до первой записи, включая даты и сетку звонков.
    slots = {number: TimeSlot(number=number, start_time=_parse_time(start), end_time=_parse_time(end))
             for number, start, end in DEFAULT_TIME_SLOTS}
    slots.update({slot.number: slot for slot in session.scalars(select(TimeSlot))})
    for file in report.files:
        parsed = file.parsed
        if parsed.week_number is not None:
            in_semester = 1 <= parsed.week_number <= semester.total_weeks
            monday = weeks.monday_of_week(semester, parsed.week_number) if in_semester else None
            if (monday is None or parsed.start_date is None
                    or not monday <= parsed.start_date <= monday + timedelta(days=6)):
                if not parsed.errors:
                    parsed.errors.append(WeeklyIssue(parsed.sheet, "", str(parsed.start_date or ""),
                                                     f"Даты книги не попадают в неделю {parsed.week_number} активного семестра"))
        file.times = _resolve_times(parsed, slots)
        for severity, issues in (("error", parsed.errors), ("warning", parsed.warnings)):
            target = report.errors if severity == "error" else report.warnings
            target.extend({"file_name": file.file_name, "severity": severity, **asdict(issue)} for issue in issues)

    if report.errors and not skip_errors:
        return report

    valid = [file for file in report.files if not file.parsed.errors]
    if not valid:
        return report
    ensure_reference_data(session)
    names = [source[1] if isinstance(source, tuple) else source for source in paths]
    record = ScheduleImport(semester_id=semester.id, file_name="; ".join(names)[:300], status="published",
                            uploaded_by=uploaded_by,
                            errors=report.errors + report.warnings or None)
    session.add(record)
    session.flush()
    report.import_id = record.id
    group_ids: set[int] = set()
    for file in valid:
        parsed = file.parsed
        group = session.scalar(select(Group).where(Group.name == parsed.group_name))
        if group is None:
            group = Group(name=parsed.group_name, course=parsed.course, direction=direction_of(parsed.group_name))
            session.add(group)
            session.flush()
            report.groups_created += 1
        elif group.direction is None:
            group.direction = direction_of(group.name)
        group_ids.add(group.id)

        condition = (Lesson.semester_id == semester.id, Lesson.group_id == group.id,
                     Lesson.week_from == parsed.week_number, Lesson.week_to == parsed.week_number)
        old_ids = select(Lesson.id).where(*condition)
        report.overrides_deleted += session.scalar(
            select(func.count()).select_from(LessonOverride).where(LessonOverride.lesson_id.in_(old_ids)))
        # Явное удаление поддерживает и SQLite-сессии без PRAGMA foreign_keys.
        session.execute(delete(LessonOverride).where(LessonOverride.lesson_id.in_(old_ids)))
        session.execute(delete(Lesson).where(*condition))
        monday = weeks.monday_of_week(semester, parsed.week_number)
        for lesson, (start, end, slot) in zip(parsed.lessons, file.times, strict=True):
            subject = _get_or_create(session, Subject, Subject.name, lesson.subject)
            teacher = _get_or_create(session, Teacher, Teacher.full_name, lesson.teacher)
            room = _get_or_create(session, Room, Room.name, lesson.room) if lesson.room else None
            session.add(Lesson(semester_id=semester.id, group_id=group.id, weekday=lesson.weekday,
                               start_time=start, end_time=end, slot=slot, week_parity="both",
                               subject_id=subject.id, lesson_type="other", teacher_id=teacher.id,
                               room_id=room.id if room else None, online_url=lesson.online_url,
                               valid_from=monday, valid_to=monday + timedelta(days=6),
                               week_from=parsed.week_number, week_to=parsed.week_number, status="published",
                               import_id=record.id, source_ref=lesson.source_ref, source_text=lesson.source_text))
            report.lessons_created += 1
        session.flush()
    report.groups_count = len(group_ids)
    record.lessons_count = report.lessons_created
    session.flush()
    return report
