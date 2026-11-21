"""Админское API: временные изменения расписания. Требует вход администратора."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import require_admin
from app.schemas.admin import CatalogOut, OverrideCreatedOut, OverrideDeletedOut, OverrideIn
from app.schemas.schedule import WeekScheduleOut
from app.services import overrides as overrides_service
from app.services import schedule as schedule_service
from app.services import stream_schedule as stream_service
from app.services import weeks as weeks_service

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.get("/stream-schedule", response_model=WeekScheduleOut, summary="Общие пары потока на неделю")
async def stream_schedule(
    group_ids: list[int] = Query(default=[]),
    week: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> WeekScheduleOut:
    try:
        groups = await stream_service.load_groups(db, group_ids)
        semester = await schedule_service.active_semester(db)
        today = datetime.now().date()
        number = week or weeks_service.current_week_number(
            semester, today, await weeks_service.last_available_week(db, semester)
        )
        info, days = await stream_service.build_stream_schedule(db, groups, semester, number, today)
    except stream_service.StreamScheduleError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except schedule_service.ScheduleError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return WeekScheduleOut.model_validate({
        "group": groups[0], "week": info.__dict__,
        "generated_at": datetime.now().astimezone(), "days": days,
    })


@router.get("/catalog", response_model=CatalogOut, summary="Предметы, преподаватели, аудитории для подсказок")
async def catalog(db: AsyncSession = Depends(get_db)) -> CatalogOut:
    return CatalogOut(**await overrides_service.catalog(db))


@router.post(
    "/overrides",
    response_model=OverrideCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Временное изменение для группы или потока",
)
async def create_override(
    data: OverrideIn,
    db: AsyncSession = Depends(get_db),
    admin: str = Depends(require_admin),
) -> OverrideCreatedOut:
    try:
        semester = await schedule_service.active_semester(db)
        batch_id, created = await overrides_service.create_overrides(db, semester, data, admin, datetime.now().date())
    except schedule_service.ScheduleError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except overrides_service.OverrideError as error:
        raise HTTPException(error.status_code, str(error)) from error

    return OverrideCreatedOut(
        batch_id=batch_id,
        override_ids=[item.id for item in created],
        group_ids=sorted({item.group_id for item in created}),
    )


@router.delete("/overrides/{override_id}", response_model=OverrideDeletedOut, summary="Откатить изменение")
async def delete_override(
    override_id: int,
    batch: bool = Query(default=False, description="Откатить для всех групп потока"),
    db: AsyncSession = Depends(get_db),
) -> OverrideDeletedOut:
    try:
        deleted = await overrides_service.delete_override(db, override_id, batch)
    except overrides_service.OverrideError as error:
        raise HTTPException(error.status_code, str(error)) from error
    return OverrideDeletedOut(deleted=deleted)
