"""Редактирование разовых событий сессии и пересдач."""
from datetime import date, time

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, Semester
from app.models.exam import ExamEvent, ExamImport
from app.schemas.exam import ExamCreate, ExamPatch
from app.services import schedule_changes
from app.services.schedule import ScheduleError, active_semester


def _history_value(value: date | time | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else value.strftime("%H:%M") if isinstance(value, time) else value


class ExamError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


async def semester(db: AsyncSession) -> Semester:
    try:
        return await active_semester(db)
    except ScheduleError as error:
        raise ExamError(str(error), 409) from error


async def list_events(db: AsyncSession, kind: str | None = None, group_id: int | None = None,
                course: int | None = None) -> list[ExamEvent]:
    statement = select(ExamEvent).where(ExamEvent.semester_id == (await semester(db)).id)
    if kind:
        statement = statement.where(ExamEvent.kind == kind)
    if group_id is not None or course is not None:
        filters = []
        if group_id is not None:
            filters.append(Group.id == group_id)
        if course is not None:
            filters.append(Group.course == course)
        statement = statement.where(ExamEvent.groups.any(and_(*filters)))
    return list(await db.scalars(statement.order_by(ExamEvent.date, ExamEvent.start_time.asc().nulls_last(), ExamEvent.id)))


async def _groups(db: AsyncSession, ids: list[int]) -> list[Group]:
    groups = list(await db.scalars(select(Group).where(Group.id.in_(ids)).order_by(Group.name)))
    if not groups or len(groups) != len(set(ids)):
        raise ExamError("Выберите существующие группы")
    return groups


async def _event(db: AsyncSession, event_id: int) -> ExamEvent:
    event = await db.scalar(select(ExamEvent).where(ExamEvent.id == event_id, ExamEvent.semester_id == (await semester(db)).id))
    if event is None:
        raise ExamError("Событие не найдено", 404)
    return event


async def create_event(db: AsyncSession, data: ExamCreate) -> ExamEvent:
    event = ExamEvent(semester_id=(await semester(db)).id, source="manual", groups=await _groups(db, data.group_ids),
                      **data.model_dump(exclude={"group_ids"}))
    db.add(event)
    await db.flush()
    await schedule_changes.record_exam(db, event, "created")
    await db.commit()
    await db.refresh(event)
    return event


async def patch_event(db: AsyncSession, event_id: int, data: ExamPatch) -> ExamEvent:
    event = await _event(db, event_id)
    before = schedule_changes.exam_snapshot(event)
    previous_groups = {group.id for group in event.groups}
    values = data.model_dump(exclude_unset=True)
    if "group_ids" in values:
        event.groups = await _groups(db, values.pop("group_ids"))
    for field, value in values.items():
        if field in ("date", "start_time", "room") and getattr(event, field) != value:
            original = dict(event.original or {})
            if field not in original:
                original[field] = _history_value(getattr(event, field))
            if _history_value(value) == original[field]:
                del original[field]
            event.original = original or None
        setattr(event, field, value)
    if before != schedule_changes.exam_snapshot(event):
        await schedule_changes.record_exam(db, event, "changed", before, previous_groups | {group.id for group in event.groups})
    await db.commit()
    await db.refresh(event)
    return event


async def cancel_event(db: AsyncSession, event_id: int, cancelled: bool) -> ExamEvent:
    event = await _event(db, event_id)
    before = schedule_changes.exam_snapshot(event)
    if event.cancelled != cancelled:
        event.cancelled = cancelled
        await schedule_changes.record_exam(db, event, "changed", before)
    await db.commit()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, event_id: int) -> None:
    event = await _event(db, event_id)
    await schedule_changes.record_exam(db, event, "removed")
    await db.delete(event)
    await db.commit()


async def import_history(db: AsyncSession) -> list[ExamImport]:
    return list(await db.scalars(select(ExamImport).order_by(ExamImport.uploaded_at.desc(), ExamImport.id.desc())))
