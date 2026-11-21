"""Номера, чётность и даты учебных недель.

Единственное место, где считается календарь семестра. Фронтенд ничего
не вычисляет -- он получает готовые номера, чётность и даты.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Semester, WeekParity
from app.models.exam import ExamEvent


@dataclass(frozen=True)
class WeekInfo:
    number: int
    parity: str
    start_date: date  # понедельник
    end_date: date  # воскресенье
    is_current: bool
    prev: int | None
    next: int | None
    schedule_pending: bool = False


def first_monday(semester: Semester) -> date:
    """Понедельник первой учебной недели.

    Дата начала семестра может быть любым днём недели (например, 1 сентября --
    вторник), поэтому отступаем к понедельнику той же недели.
    """
    return semester.start_date - timedelta(days=semester.start_date.weekday())


def monday_of_week(semester: Semester, number: int) -> date:
    return first_monday(semester) + timedelta(weeks=number - 1)


def parity_of_week(semester: Semester, number: int) -> str:
    """Чётность чередуется от первой недели семестра."""
    first_is_odd = semester.first_week_parity == WeekParity.ODD.value
    number_is_odd = number % 2 == 1
    return WeekParity.ODD.value if number_is_odd == first_is_odd else WeekParity.EVEN.value


def last_available_week(session: Session, semester: Semester) -> int:
    """Единая граница расписания: учебные недели и события семестра."""
    last_date = session.scalar(select(func.max(ExamEvent.date)).where(ExamEvent.semester_id == semester.id))
    event_week = (last_date - first_monday(semester)).days // 7 + 1 if last_date else 0
    return max(semester.total_weeks, event_week)


def week_number_for_date(semester: Semester, day: date, last_week: int | None = None) -> int | None:
    """Номер учебной недели, в которую попадает дата. None -- вне семестра."""
    delta = (day - first_monday(semester)).days
    if delta < 0:
        return None
    number = delta // 7 + 1
    return number if number <= (last_week or semester.total_weeks) else None


def current_week_number(semester: Semester, today: date, last_week: int | None = None) -> int:
    """Номер текущей недели, прижатый к границам семестра.

    До начала семестра -- первая неделя, после конца -- последняя. Так
    расписание открывается всегда, а не отдаёт ошибку на каникулах.

    В воскресенье пар нет, поэтому текущей считается следующая неделя:
    студент сразу видит расписание на понедельник.
    """
    if today.isoweekday() == 7:
        today += timedelta(days=1)
    number = week_number_for_date(semester, today, last_week)
    if number is not None:
        return number
    return 1 if today < first_monday(semester) else (last_week or semester.total_weeks)


def build_week_info(semester: Semester, number: int, today: date, last_week: int | None = None) -> WeekInfo:
    monday = monday_of_week(semester, number)
    return WeekInfo(
        number=number,
        parity=parity_of_week(semester, number),
        start_date=monday,
        end_date=monday + timedelta(days=6),
        is_current=number == current_week_number(semester, today, last_week),
        prev=number - 1 if number > 1 else None,
        next=number + 1 if number < (last_week or semester.total_weeks) else None,
    )
