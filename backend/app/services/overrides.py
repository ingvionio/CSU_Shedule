"""Временные изменения расписания: создание и откат.

Одно действие админа (отмена, перенос, замена, доп. пара) может касаться
нескольких групп потока. Тогда на каждую группу создаётся своя запись
`lesson_overrides` с общим `batch_id`. Действие применяется целиком или
не применяется вовсе: при любой ошибке ничего не сохраняется.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Group,
    Lesson,
    LessonOverride,
    LessonStatus,
    LessonType,
    OverrideKind,
    PublishStatus,
    Room,
    Semester,
    Subject,
    Teacher,
    TimeSlot,
)
from app.schemas.admin import OverrideIn
from app.services import schedule as schedule_service
from app.services import weeks
from app.services.importer import _get_or_create

# Пары с такими статусами не занимают время и не мешают новой паре.
FREE_STATUSES = {LessonStatus.CANCELLED.value, LessonStatus.MOVED_OUT.value}


class OverrideError(Exception):
    """Изменение нельзя применить. `status_code` уходит в ответ API."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Timing:
    start: time
    end: time
    slot: int | None


def create_overrides(
    session: Session, semester: Semester, data: OverrideIn, created_by: str, today: date
) -> tuple[str, list[LessonOverride]]:
    """Создаёт изменение для всех групп из `data.group_ids`. Возвращает batch_id и записи."""
    groups = _load_groups(session, data.group_ids)
    _check_date(semester, data.date)

    kind = data.kind
    source: Lesson | None = None
    if kind != OverrideKind.ADD.value:
        if data.source_lesson_id is None:
            raise OverrideError("не указана исходная пара (source_lesson_id)")
        source = session.get(Lesson, data.source_lesson_id)
        if source is None or source.semester_id != semester.id:
            raise OverrideError(f"пара {data.source_lesson_id} не найдена", 404)
        if not schedule_service.lesson_occurs_on(semester, source, data.date):
            raise OverrideError(f"пары «{source.subject.name}» нет в расписании {data.date:%d.%m.%Y}")

    if kind == OverrideKind.MOVE.value:
        if data.target_date is None:
            raise OverrideError("для переноса нужна новая дата (target_date)")
        _check_date(semester, data.target_date)
        if data.slot is None and data.start_time is None:
            raise OverrideError("для переноса нужно новое время: номер пары или start_time/end_time")
    if kind == OverrideKind.ADD.value:
        if not (data.subject or "").strip():
            raise OverrideError("для новой пары нужна дисциплина")
        if data.slot is None and data.start_time is None:
            raise OverrideError("для новой пары нужно время: номер пары или start_time/end_time")

    timing = _resolve_timing(session, data)
    lesson_type = _resolve_lesson_type(session, data.lesson_type)

    batch_id = str(uuid.uuid4())
    created: list[LessonOverride] = []
    missing: list[str] = []

    for group in groups:
        if kind == OverrideKind.ADD.value:
            created.append(_build(session, semester, group, data, batch_id, created_by, None, None, timing, lesson_type))
            continue

        targets = [source] if source.group_id == group.id else _matching_lessons(session, semester, source, group, data.date)
        if not targets:
            missing.append(group.name)
            continue
        for lesson in targets:
            # Новое изменение пары на ту же дату заменяет прежнее.
            session.execute(
                delete(LessonOverride).where(LessonOverride.lesson_id == lesson.id, LessonOverride.date == data.date)
            )
            created.append(_build(session, semester, group, data, batch_id, created_by, lesson, source, timing, lesson_type))

    if missing:
        message = (
            f"у групп {', '.join(missing)} нет пары «{source.subject.name}» "
            f"{data.date:%d.%m.%Y} в {source.start_time:%H:%M}"
        )
        session.rollback()
        raise OverrideError(message)

    session.add_all(created)
    session.flush()

    try:
        _check_conflicts(session, semester, created, today)
    except OverrideError:
        session.rollback()
        raise

    session.commit()
    return batch_id, created


def delete_override(session: Session, override_id: int, whole_batch: bool) -> int:
    """Откатывает изменение. `whole_batch` — для всех групп, к которым оно применялось."""
    override = session.get(LessonOverride, override_id)
    if override is None:
        raise OverrideError(f"изменение {override_id} не найдено", 404)

    condition = (
        LessonOverride.batch_id == override.batch_id if whole_batch else LessonOverride.id == override.id
    )
    deleted = session.execute(delete(LessonOverride).where(condition)).rowcount
    session.commit()
    return deleted


def catalog(session: Session) -> dict[str, list[str]]:
    return {
        "subjects": list(session.scalars(select(Subject.name).order_by(Subject.name))),
        "teachers": list(session.scalars(select(Teacher.full_name).order_by(Teacher.full_name))),
        "rooms": list(session.scalars(select(Room.name).order_by(Room.name))),
    }


def _load_groups(session: Session, group_ids: list[int]) -> list[Group]:
    unique_ids = list(dict.fromkeys(group_ids))
    groups = {group.id: group for group in session.scalars(select(Group).where(Group.id.in_(unique_ids)))}
    unknown = [str(group_id) for group_id in unique_ids if group_id not in groups]
    if unknown:
        raise OverrideError(f"группы не найдены: {', '.join(unknown)}", 404)
    return [groups[group_id] for group_id in unique_ids]


def _check_date(semester: Semester, day: date) -> None:
    if weeks.week_number_for_date(semester, day) is None:
        raise OverrideError(f"дата {day:%d.%m.%Y} вне семестра")
    if day.isoweekday() == 7:
        raise OverrideError(f"{day:%d.%m.%Y} — воскресенье, занятий в этот день нет")


def _parse_time(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def _resolve_timing(session: Session, data: OverrideIn) -> _Timing | None:
    """Новое время из запроса. None — время не меняется.

    Своё время, совпавшее со звонком, получает номер пары; иначе пара вне сетки.
    """
    if data.start_time is not None:
        if data.end_time is None:
            raise OverrideError("укажите время окончания пары (end_time)")
        start, end = _parse_time(data.start_time), _parse_time(data.end_time)
        if end <= start:
            raise OverrideError("пара должна заканчиваться позже, чем начинается")
        slot = session.scalar(select(TimeSlot).where(TimeSlot.start_time == start, TimeSlot.end_time == end))
        return _Timing(start, end, slot.number if slot else None)

    if data.slot is not None:
        slot = session.get(TimeSlot, data.slot)
        if slot is None:
            raise OverrideError(f"в сетке звонков нет {data.slot} пары")
        return _Timing(slot.start_time, slot.end_time, slot.number)

    return None


def _resolve_lesson_type(session: Session, code: str | None) -> LessonType | None:
    if code is None:
        return None
    lesson_type = session.get(LessonType, code)
    if lesson_type is None:
        raise OverrideError(f"неизвестный формат пары: {code}")
    return lesson_type


def _matching_lessons(
    session: Session, semester: Semester, source: Lesson, group: Group, day: date
) -> list[Lesson]:
    """Та же пара у другой группы потока: тот же день, время и предмет."""
    candidates = session.scalars(
        select(Lesson).where(
            Lesson.group_id == group.id,
            Lesson.semester_id == semester.id,
            Lesson.status == PublishStatus.PUBLISHED.value,
            Lesson.weekday == source.weekday,
            Lesson.start_time == source.start_time,
            Lesson.subject_id == source.subject_id,
        )
    ).all()
    return [lesson for lesson in candidates if schedule_service.lesson_occurs_on(semester, lesson, day)]


def _pick(requested, source_value, own_value):
    """Значение поля итоговой пары.

    Не передано или совпадает с исходной парой — берётся значение своей пары
    группы (у групп потока могут быть свои аудитории и преподаватели).
    """
    if requested is None or requested == source_value:
        return own_value
    return requested


def _build(
    session: Session,
    semester: Semester,
    group: Group,
    data: OverrideIn,
    batch_id: str,
    created_by: str,
    lesson: Lesson | None,
    source: Lesson | None,
    timing: _Timing | None,
    lesson_type: LessonType | None,
) -> LessonOverride:
    override = LessonOverride(
        semester_id=semester.id,
        group_id=group.id,
        kind=data.kind,
        date=data.date,
        lesson=lesson,
        target_date=data.target_date if data.kind == OverrideKind.MOVE.value else None,
        comment=(data.comment or "").strip() or None,
        batch_id=batch_id,
        status=PublishStatus.PUBLISHED.value,
        created_by=created_by,
    )
    if data.kind == OverrideKind.CANCEL.value:
        return override

    def own(attr: str):
        return getattr(lesson, attr) if lesson is not None else None

    def from_source(attr: str):
        return getattr(source, attr) if source is not None else None

    # Время: своё время группы сохраняется, если админ его не менял.
    keep_own_time = lesson is not None and (
        timing is None or (timing.start, timing.end) == (source.start_time, source.end_time)
    )
    if keep_own_time:
        override.start_time, override.end_time, override.slot = lesson.start_time, lesson.end_time, lesson.slot
    else:
        override.start_time, override.end_time, override.slot = timing.start, timing.end, timing.slot

    subject_name = _pick(_clean(data.subject), _name(from_source("subject")), _name(own("subject")))
    override.subject = _get_or_create(session, Subject, Subject.name, subject_name)

    type_code = _pick(lesson_type.code if lesson_type else None, from_source("lesson_type"), own("lesson_type"))
    override.type = session.get(LessonType, type_code or "other")

    teacher_name = _pick(_clean(data.teacher), _name(from_source("teacher")) or "", _name(own("teacher")) or "")
    override.teacher = _get_or_create(session, Teacher, Teacher.full_name, teacher_name) if teacher_name else None

    room_name = _pick(_clean(data.room), _name(from_source("room")) or "", _name(own("room")) or "")
    override.room = _get_or_create(session, Room, Room.name, room_name) if room_name else None

    override.subgroup = own("subgroup")
    return override


def _clean(value: str | None) -> str | None:
    return value.strip() if value is not None else None


def _name(entity) -> str | None:
    if entity is None:
        return None
    return getattr(entity, "name", None) or getattr(entity, "full_name", None)


def _check_conflicts(session: Session, semester: Semester, created: list[LessonOverride], today: date) -> None:
    """Новая пара не должна пересекаться по времени с другими парами группы.

    Отменённые и перенесённые пары время не занимают. Пары разных подгрупп
    могут стоять одновременно.
    """
    for override in created:
        if override.kind == OverrideKind.CANCEL.value:
            continue

        day = override.target_date if override.kind == OverrideKind.MOVE.value else override.date
        item_id = f"l-{override.lesson_id}" if override.kind == OverrideKind.REPLACE.value else f"o-{override.id}"
        group = session.get(Group, override.group_id)
        built = schedule_service.build_day(session, group, semester, day, today)

        mine = next(item for item in built["lessons"] if item["id"] == item_id)
        for other in built["lessons"]:
            if other["id"] == item_id or other["status"] in FREE_STATUSES:
                continue
            if mine["subgroup"] and other["subgroup"] and mine["subgroup"] != other["subgroup"]:
                continue
            if mine["start_time"] < other["end_time"] and other["start_time"] < mine["end_time"]:
                raise OverrideError(
                    f"{group.name}, {day:%d.%m.%Y}: пара {mine['start_time']}–{mine['end_time']} "
                    f"пересекается с «{other['subject']}» {other['start_time']}–{other['end_time']}",
                    409,
                )
