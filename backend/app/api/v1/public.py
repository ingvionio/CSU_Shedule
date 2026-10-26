"""Публичное API для студента."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Group, LessonType, TimeSlot
from app.schemas.schedule import (
    CurrentWeekOut,
    DirectionOut,
    GroupOut,
    LessonTypeOut,
    SemesterOut,
    TimeSlotOut,
    WeekScheduleOut,
)
from app.core.config import get_settings
from app.schemas.student import PushConfigOut
from app.services import push as push_service
from app.services import schedule as schedule_service
from app.services import weeks as weeks_service

router = APIRouter()


def _today():
    return datetime.now().date()


@router.get("/groups", response_model=list[GroupOut], summary="Список групп")
def list_groups(db: Session = Depends(get_db)) -> list[Group]:
    return list(db.scalars(select(Group).order_by(Group.course, Group.name)).all())


@router.get("/directions", response_model=list[DirectionOut], summary="Направления подготовки (потоки)")
def list_directions(db: Session = Depends(get_db)) -> list[DirectionOut]:
    rows = db.execute(
        select(Group.direction, Group.course)
        .where(Group.direction.is_not(None))
        .distinct()
        .order_by(Group.direction, Group.course)
    ).all()
    courses: dict[str, list[int]] = {}
    for direction, course in rows:
        courses.setdefault(direction, []).append(course)
    return [DirectionOut(code=code, courses=items) for code, items in courses.items()]


@router.get("/push/config", response_model=PushConfigOut, summary="Публичный VAPID-ключ для подписки на push")
def push_config() -> PushConfigOut:
    return PushConfigOut(public_key=get_settings().vapid_public_key if push_service.is_configured() else None)


@router.get("/time-slots", response_model=list[TimeSlotOut], summary="Сетка звонков")
def list_time_slots(db: Session = Depends(get_db)) -> list[TimeSlotOut]:
    slots = db.scalars(select(TimeSlot).order_by(TimeSlot.number)).all()
    return [
        TimeSlotOut(
            number=slot.number,
            start_time=slot.start_time.strftime("%H:%M"),
            end_time=slot.end_time.strftime("%H:%M"),
        )
        for slot in slots
    ]


@router.get("/lesson-types", response_model=list[LessonTypeOut], summary="Форматы пар")
def list_lesson_types(db: Session = Depends(get_db)) -> list[LessonTypeOut]:
    types = db.scalars(select(LessonType).order_by(LessonType.name)).all()
    return [LessonTypeOut(code=item.code, name=item.name) for item in types]


@router.get("/weeks/current", response_model=CurrentWeekOut, summary="Текущая учебная неделя")
def current_week(db: Session = Depends(get_db)) -> CurrentWeekOut:
    try:
        semester = schedule_service.active_semester(db)
    except schedule_service.ScheduleError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    today = _today()
    number = weeks_service.current_week_number(semester, today)
    info = weeks_service.build_week_info(semester, number, today)

    return CurrentWeekOut(
        number=info.number,
        parity=info.parity,
        start_date=info.start_date,
        end_date=info.end_date,
        semester=SemesterOut(id=semester.id, title=semester.title, total_weeks=semester.total_weeks),
    )


@router.get(
    "/groups/{group_id}/schedule",
    response_model=WeekScheduleOut,
    summary="Расписание группы на неделю",
)
def group_schedule(
    group_id: int,
    week: int | None = Query(default=None, ge=1, description="Номер недели; без него -- текущая"),
    db: Session = Depends(get_db),
) -> WeekScheduleOut:
    try:
        semester = schedule_service.active_semester(db)
        group = schedule_service.get_group(db, group_id)
        today = _today()
        week_number = week or weeks_service.current_week_number(semester, today)
        info, days = schedule_service.build_week_schedule(db, group, semester, week_number, today)
    except schedule_service.ScheduleError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return WeekScheduleOut.model_validate(
        {
            "group": group,
            "week": info.__dict__,
            "generated_at": datetime.now().astimezone(),
            "days": days,
        }
    )
