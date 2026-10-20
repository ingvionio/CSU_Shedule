"""Загрузка разобранного Excel в базу.

Парсер (`excel_parser`) не знает о БД; импортёр берёт его результат,
дозаполняет справочники и создаёт постоянные пары.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Group,
    ImportStatus,
    Lesson,
    LessonType,
    PublishStatus,
    Room,
    ScheduleImport,
    Semester,
    Subject,
    Teacher,
    TimeSlot,
)
from app.services import weeks
from app.services.excel_parser import ParsedLesson, ParseResult, parse_workbook

# Форматы пар. Таблица, а не enum — список расширяется без миграции.
DEFAULT_LESSON_TYPES: list[tuple[str, str]] = [
    ("lecture", "Лекция"),
    ("practice", "Практика"),
    ("lab", "Лабораторная"),
    ("lecture_practice", "Лекция и практика"),
    ("other", "Занятие"),
]

# Сетка звонков ЧелГУ: номер пары -> начало и конец.
DEFAULT_TIME_SLOTS: list[tuple[int, str, str]] = [
    (1, "08:00", "09:30"),
    (2, "09:40", "11:10"),
    (3, "11:20", "12:50"),
    (4, "13:15", "14:45"),
    (5, "15:00", "16:30"),
    (6, "16:40", "18:10"),
    (7, "18:20", "19:50"),
    (8, "19:55", "21:25"),
]


@dataclass
class ImportReport:
    import_id: int
    groups_created: int
    lessons_created: int
    warnings: int
    semester_title: str


def _parse_time(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def ensure_reference_data(session: Session) -> None:
    """Создаёт сетку звонков и форматы пар, если их ещё нет."""
    for code, name in DEFAULT_LESSON_TYPES:
        if session.get(LessonType, code) is None:
            session.add(LessonType(code=code, name=name))

    for number, start, end in DEFAULT_TIME_SLOTS:
        if session.get(TimeSlot, number) is None:
            session.add(TimeSlot(number=number, start_time=_parse_time(start), end_time=_parse_time(end)))

    session.flush()


def _get_or_create(session: Session, model: type, column, value: str):
    """Находит запись справочника по значению или создаёт её."""
    instance = session.scalar(select(model).where(column == value))
    if instance is None:
        instance = model(**{column.key: value})
        session.add(instance)
        session.flush()
    return instance


def _lesson_times(
    slots: dict[int, TimeSlot], parsed: ParsedLesson
) -> tuple[time, time, int | None]:
    """Время пары и номер в сетке звонков.

    Пара со своим временем ("с 19:00") хранится вне сетки: slot = None,
    длительность берём такую же, как у соответствующего номера в сетке.
    """
    slot = slots[parsed.slot]
    if parsed.custom_start is None:
        return slot.start_time, slot.end_time, parsed.slot

    anchor = date(2000, 1, 1)
    duration = datetime.combine(anchor, slot.end_time) - datetime.combine(anchor, slot.start_time)
    start = _parse_time(parsed.custom_start)
    end = (datetime.combine(anchor, start) + duration).time()
    return start, end, None


def _validity_dates(semester: Semester, parsed: ParsedLesson) -> tuple[object, object]:
    """Срок действия пары из ограничения вида "(9-15 НЕД.)"."""
    semester_start = weeks.first_monday(semester)
    if parsed.week_from is None:
        return semester_start, semester.end_date

    valid_from = weeks.monday_of_week(semester, parsed.week_from)
    valid_to = (
        weeks.monday_of_week(semester, parsed.week_to) + timedelta(days=6)
        if parsed.week_to is not None
        else semester.end_date
    )
    return valid_from, min(valid_to, semester.end_date)


def import_workbook(
    session: Session,
    path: str,
    semester: Semester,
    file_name: str | None = None,
    replace: bool = True,
) -> ImportReport:
    """Разбирает файл и записывает расписание в базу.

    `replace=True` удаляет ранее импортированные пары этого семестра --
    повторный запуск не плодит дубликаты.
    """
    result: ParseResult = parse_workbook(path)
    ensure_reference_data(session)

    record = ScheduleImport(
        semester_id=semester.id,
        file_name=file_name or path,
        status=ImportStatus.PARSED.value,
        errors=[asdict(error) for error in result.errors] or None,
    )
    session.add(record)
    session.flush()

    groups_created = 0
    group_ids: dict[str, int] = {}
    for parsed_group in result.groups:
        group = session.scalar(select(Group).where(Group.name == parsed_group.name))
        if group is None:
            group = Group(name=parsed_group.name, course=parsed_group.course)
            session.add(group)
            session.flush()
            groups_created += 1
        group_ids[parsed_group.name] = group.id

    if replace:
        session.execute(delete(Lesson).where(Lesson.semester_id == semester.id))
        session.flush()

    slots = {slot.number: slot for slot in session.scalars(select(TimeSlot)).all()}

    for parsed in result.lessons:
        group_id = group_ids.get(parsed.group_name)
        if group_id is None or parsed.slot not in slots:
            continue

        start_time, end_time, slot_number = _lesson_times(slots, parsed)
        valid_from, valid_to = _validity_dates(semester, parsed)

        subject = _get_or_create(session, Subject, Subject.name, parsed.subject)
        teacher = (
            _get_or_create(session, Teacher, Teacher.full_name, parsed.teacher) if parsed.teacher else None
        )
        room = _get_or_create(session, Room, Room.name, parsed.room) if parsed.room else None

        session.add(
            Lesson(
                semester_id=semester.id,
                group_id=group_id,
                weekday=parsed.weekday,
                start_time=start_time,
                end_time=end_time,
                slot=slot_number,
                week_parity=parsed.parity,
                subject_id=subject.id,
                lesson_type=parsed.lesson_type,
                teacher_id=teacher.id if teacher else None,
                room_id=room.id if room else None,
                valid_from=valid_from,
                valid_to=valid_to,
                week_from=parsed.week_from,
                week_to=parsed.week_to,
                subgroup=parsed.subgroup,
                status=PublishStatus.PUBLISHED.value,
                import_id=record.id,
                source_ref=f"{parsed.sheet}!{parsed.source_ref}",
                source_text=parsed.source_text,
            )
        )

    record.lessons_count = len(result.lessons)
    record.status = ImportStatus.PUBLISHED.value
    session.commit()

    return ImportReport(
        import_id=record.id,
        groups_created=groups_created,
        lessons_created=len(result.lessons),
        warnings=len(result.errors),
        semester_title=semester.title,
    )
