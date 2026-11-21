"""Публичное API для студента."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
async def list_groups(db: AsyncSession = Depends(get_db)) -> list[Group]:
    return list((await db.scalars(select(Group).order_by(Group.course, Group.name))).all())


@router.get("/directions", response_model=list[DirectionOut], summary="Направления подготовки (потоки)")
async def list_directions(db: AsyncSession = Depends(get_db)) -> list[DirectionOut]:
    rows = (await db.execute(
        select(Group.direction, Group.course)
        .where(Group.direction.is_not(None))
        .distinct()
        .order_by(Group.direction, Group.course)
    )).all()
    courses: dict[str, list[int]] = {}
    for direction, course in rows:
        courses.setdefault(direction, []).append(course)
    return [DirectionOut(code=code, courses=items) for code, items in courses.items()]


@router.get("/push/config", response_model=PushConfigOut, summary="Настройки Web Push и FCM для подписки")
async def push_config() -> PushConfigOut:
    return PushConfigOut(
        public_key=get_settings().vapid_public_key if push_service.web_configured() else None,
        fcm=push_service.fcm_configured(),
    )


@router.get("/time-slots", response_model=list[TimeSlotOut], summary="Сетка звонков")
async def list_time_slots(db: AsyncSession = Depends(get_db)) -> list[TimeSlotOut]:
    slots = (await db.scalars(select(TimeSlot).order_by(TimeSlot.number))).all()
    return [
        TimeSlotOut(
            number=slot.number,
            start_time=slot.start_time.strftime("%H:%M"),
            end_time=slot.end_time.strftime("%H:%M"),
        )
        for slot in slots
    ]


@router.get("/lesson-types", response_model=list[LessonTypeOut], summary="Форматы пар")
async def list_lesson_types(db: AsyncSession = Depends(get_db)) -> list[LessonTypeOut]:
    types = (await db.scalars(select(LessonType).order_by(LessonType.name))).all()
    return [LessonTypeOut(code=item.code, name=item.name) for item in types]


@router.get("/weeks/current", response_model=CurrentWeekOut, summary="Текущая учебная неделя")
async def current_week(db: AsyncSession = Depends(get_db)) -> CurrentWeekOut:
    try:
        semester = await schedule_service.active_semester(db)
    except schedule_service.ScheduleError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    today = _today()
    last_week = await weeks_service.last_available_week(db, semester)
    number = weeks_service.current_week_number(semester, today, last_week)
    info = weeks_service.build_week_info(semester, number, today, last_week)

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
async def group_schedule(
    group_id: int,
    week: int | None = Query(default=None, ge=1, description="Номер недели; без него -- текущая"),
    # Старые клиенты (APK 1.1.1) не умеют события без времени и падают на них —
    # экзамены получают только клиенты, которые явно об этом просят.
    events: bool = Query(default=False, description="Включить события сессии и пересдач"),
    db: AsyncSession = Depends(get_db),
) -> WeekScheduleOut:
    try:
        semester = await schedule_service.active_semester(db)
        group = await schedule_service.get_group(db, group_id)
        today = _today()
        week_number = week or weeks_service.current_week_number(
            semester, today, await weeks_service.last_available_week(db, semester)
        )
        info, days = await schedule_service.build_week_schedule(
            db, group, semester, week_number, today, include_exams=events
        )
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
