"""Сборка расписания группы на неделю.

Ядро бэкенда: по группе и номеру недели отбирает постоянные пары с учётом
чётности и срока действия, применяет к ним временные изменения
(`lesson_overrides`) и отдаёт готовую структуру.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Group,
    Lesson,
    LessonOverride,
    LessonStatus,
    OverrideKind,
    PublishStatus,
    Semester,
    WeekParity,
)
from app.services import weeks
from app.services.weeks import WeekInfo

# Поля пары, которые может поменять `replace`; их прежние значения уходят в change.original.
CHANGEABLE_FIELDS = ("start_time", "end_time", "slot", "subject", "type", "room", "teacher")


class ScheduleError(Exception):
    """Расписание не может быть собрано (нет семестра, группы или недели)."""


def active_semester(session: Session) -> Semester:
    semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
    if semester is None:
        raise ScheduleError("активный семестр не настроен")
    return semester


def get_group(session: Session, group_id: int) -> Group:
    group = session.get(Group, group_id)
    if group is None:
        raise ScheduleError(f"группа {group_id} не найдена")
    return group


def build_week_schedule(
    session: Session,
    group: Group,
    semester: Semester,
    week_number: int,
    today: date,
) -> tuple[WeekInfo, list[dict]]:
    """Возвращает информацию о неделе и дни недели с парами.

    Дни отдаются пн-сб целиком, включая дни без пар.
    """
    if not 1 <= week_number <= semester.total_weeks:
        raise ScheduleError(
            f"неделя {week_number} вне семестра (1..{semester.total_weeks})"
        )

    week = weeks.build_week_info(semester, week_number, today)
    return week, _assemble_days(session, group, semester, week, today)


def build_day(session: Session, group: Group, semester: Semester, day: date, today: date) -> dict:
    """Один собранный день — для проверки пересечений при создании изменений."""
    number = weeks.week_number_for_date(semester, day)
    if number is None:
        raise ScheduleError(f"дата {day:%d.%m.%Y} вне семестра")
    week = weeks.build_week_info(semester, number, today)
    return next(item for item in _assemble_days(session, group, semester, week, today) if item["date"] == day)


def lesson_occurs_on(semester: Semester, lesson: Lesson, day: date) -> bool:
    """Стоит ли постоянная пара в расписании на эту дату."""
    number = weeks.week_number_for_date(semester, day)
    if number is None or lesson.weekday != day.isoweekday():
        return False
    if lesson.week_parity not in (weeks.parity_of_week(semester, number), WeekParity.BOTH.value):
        return False
    return _is_valid_on(lesson, day)


def _assemble_days(
    session: Session, group: Group, semester: Semester, week: WeekInfo, today: date
) -> list[dict]:
    lessons = session.scalars(
        select(Lesson)
        .where(
            Lesson.group_id == group.id,
            Lesson.semester_id == semester.id,
            Lesson.status == PublishStatus.PUBLISHED.value,
            Lesson.week_parity.in_([week.parity, WeekParity.BOTH.value]),
        )
        .order_by(Lesson.weekday, Lesson.start_time)
    ).all()

    # Изменения, у которых исходная или новая дата попадает в неделю:
    # перенос может пересекать границу недели.
    overrides = session.scalars(
        select(LessonOverride).where(
            LessonOverride.group_id == group.id,
            LessonOverride.semester_id == semester.id,
            LessonOverride.status == PublishStatus.PUBLISHED.value,
            or_(
                LessonOverride.date.between(week.start_date, week.end_date),
                LessonOverride.target_date.between(week.start_date, week.end_date),
            ),
        )
    ).unique().all()
    by_source = {(item.lesson_id, item.date): item for item in overrides if item.lesson_id is not None}

    days: list[dict] = []
    for offset in range(6):  # пн..сб
        day_date = week.start_date + timedelta(days=offset)
        weekday = offset + 1

        day_lessons = [
            _apply_override(lesson, by_source.get((lesson.id, day_date)))
            for lesson in lessons
            if lesson.weekday == weekday and _is_valid_on(lesson, day_date)
        ]
        for override in overrides:
            if override.kind == OverrideKind.ADD.value and override.date == day_date:
                day_lessons.append(_serialize_added(override))
            elif override.kind == OverrideKind.MOVE.value and override.target_date == day_date:
                day_lessons.append(_serialize_moved_in(override))

        day_lessons.sort(key=lambda item: (item["start_time"], item["subject"]))

        days.append(
            {
                "date": day_date,
                "weekday": weekday,
                "is_today": day_date == today,
                "lessons": day_lessons,
            }
        )

    return days


def _is_valid_on(lesson: Lesson, day: date) -> bool:
    """Действует ли пара в эту дату (ограничения вида "(9-15 НЕД.)")."""
    if lesson.valid_from and day < lesson.valid_from:
        return False
    if lesson.valid_to and day > lesson.valid_to:
        return False
    return True


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _point(day: date, slot: int | None, start: time, end: time) -> dict:
    """Куда / откуда перенесена пара."""
    return {"date": day.isoformat(), "slot": slot, "start_time": _hhmm(start), "end_time": _hhmm(end)}


def _change(override: LessonOverride, **details) -> dict:
    return {
        "override_id": override.id,
        "kind": override.kind,
        "comment": override.comment,
        "original": None,
        "moved_to": None,
        "moved_from": None,
        **details,
    }


def _serialize_lesson(lesson: Lesson) -> dict:
    return {
        "id": f"l-{lesson.id}",
        "start_time": _hhmm(lesson.start_time),
        "end_time": _hhmm(lesson.end_time),
        "slot": lesson.slot,
        "subject": lesson.subject.name,
        "type": {"code": lesson.type.code, "name": lesson.type.name},
        "room": lesson.room.name if lesson.room else None,
        "teacher": lesson.teacher.full_name if lesson.teacher else None,
        "subgroup": lesson.subgroup,
        "status": LessonStatus.REGULAR.value,
        "change": None,
    }


def _override_fields(override: LessonOverride) -> dict:
    """Поля итоговой пары из изменения (move / replace / add)."""
    return {
        "start_time": _hhmm(override.start_time),
        "end_time": _hhmm(override.end_time),
        "slot": override.slot,
        "subject": override.subject.name,
        "type": {"code": override.type.code, "name": override.type.name},
        "room": override.room.name if override.room else None,
        "teacher": override.teacher.full_name if override.teacher else None,
        "subgroup": override.subgroup,
    }


def _apply_override(lesson: Lesson, override: LessonOverride | None) -> dict:
    """Постоянная пара с применённым изменением на её дату."""
    item = _serialize_lesson(lesson)
    if override is None:
        return item

    if override.kind == OverrideKind.CANCEL.value:
        return {**item, "status": LessonStatus.CANCELLED.value, "change": _change(override)}

    if override.kind == OverrideKind.MOVE.value:
        moved_to = _point(override.target_date, override.slot, override.start_time, override.end_time)
        return {**item, "status": LessonStatus.MOVED_OUT.value, "change": _change(override, moved_to=moved_to)}

    # replace: поля заменяются, прежние значения — в original.
    replaced = {**item, **_override_fields(override)}
    original = {field: item[field] for field in CHANGEABLE_FIELDS if item[field] != replaced[field]}
    return {
        **replaced,
        "status": LessonStatus.CHANGED.value,
        "change": _change(override, original=original or None),
    }


def _serialize_added(override: LessonOverride) -> dict:
    return {
        "id": f"o-{override.id}",
        **_override_fields(override),
        "status": LessonStatus.ADDED.value,
        "change": _change(override),
    }


def _serialize_moved_in(override: LessonOverride) -> dict:
    source = override.lesson
    moved_from = _point(override.date, source.slot, source.start_time, source.end_time)
    return {
        "id": f"o-{override.id}",
        **_override_fields(override),
        "status": LessonStatus.MOVED_IN.value,
        "change": _change(override, moved_from=moved_from),
    }
