"""Сборка расписания группы на неделю.

Ядро бэкенда: по группе и номеру недели отбирает постоянные пары с учётом
чётности и срока действия и отдаёт готовую структуру. На этом этапе
временных изменений нет, поэтому у всех пар статус `regular`.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Group, Lesson, PublishStatus, Semester, WeekParity
from app.services import weeks
from app.services.weeks import WeekInfo


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
    parity = week.parity

    lessons = session.scalars(
        select(Lesson)
        .where(
            Lesson.group_id == group.id,
            Lesson.semester_id == semester.id,
            Lesson.status == PublishStatus.PUBLISHED.value,
            Lesson.week_parity.in_([parity, WeekParity.BOTH.value]),
        )
        .order_by(Lesson.weekday, Lesson.start_time)
    ).all()

    days: list[dict] = []
    for offset in range(6):  # пн..сб
        day_date = week.start_date + timedelta(days=offset)
        weekday = offset + 1

        day_lessons = [
            _serialize_lesson(lesson)
            for lesson in lessons
            if lesson.weekday == weekday and _is_valid_on(lesson, day_date)
        ]
        day_lessons.sort(key=lambda item: (item["start_time"], item["subject"]))

        days.append(
            {
                "date": day_date,
                "weekday": weekday,
                "is_today": day_date == today,
                "lessons": day_lessons,
            }
        )

    return week, days


def _is_valid_on(lesson: Lesson, day: date) -> bool:
    """Действует ли пара в эту дату (ограничения вида "(9-15 НЕД.)")."""
    if lesson.valid_from and day < lesson.valid_from:
        return False
    if lesson.valid_to and day > lesson.valid_to:
        return False
    return True


def _serialize_lesson(lesson: Lesson) -> dict:
    return {
        "id": f"l-{lesson.id}",
        "start_time": lesson.start_time.strftime("%H:%M"),
        "end_time": lesson.end_time.strftime("%H:%M"),
        "slot": lesson.slot,
        "subject": lesson.subject.name,
        "type": {"code": lesson.type.code, "name": lesson.type.name},
        "room": lesson.room.name if lesson.room else None,
        "teacher": lesson.teacher.full_name if lesson.teacher else None,
        "subgroup": lesson.subgroup,
        "status": "regular",
        "change": None,
    }
