"""Редактирование разовых событий и готовый список для студента."""
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import Group, Semester
from app.models.exam import ExamEvent, ExamImport
from app.schemas.exam import ExamCreate, ExamPatch, GroupExamsOut
from app.services.schedule import ScheduleError, active_semester

KIND_NAMES = {"session": "Сессия", "retake": "Пересдача"}


class ExamError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def today() -> date:
    return date.today()


def semester(db: Session) -> Semester:
    try:
        return active_semester(db)
    except ScheduleError as error:
        raise ExamError(str(error), 409) from error


def list_events(db: Session, kind: str | None = None, group_id: int | None = None,
                course: int | None = None) -> list[ExamEvent]:
    statement = select(ExamEvent).where(ExamEvent.semester_id == semester(db).id)
    if kind:
        statement = statement.where(ExamEvent.kind == kind)
    if group_id is not None or course is not None:
        filters = []
        if group_id is not None:
            filters.append(Group.id == group_id)
        if course is not None:
            filters.append(Group.course == course)
        statement = statement.where(ExamEvent.groups.any(and_(*filters)))
    return list(db.scalars(statement.order_by(ExamEvent.date, ExamEvent.start_time.asc().nulls_last(), ExamEvent.id)))


def _groups(db: Session, ids: list[int]) -> list[Group]:
    groups = list(db.scalars(select(Group).where(Group.id.in_(ids)).order_by(Group.name)))
    if not groups or len(groups) != len(set(ids)):
        raise ExamError("Выберите существующие группы")
    return groups


def _event(db: Session, event_id: int) -> ExamEvent:
    event = db.scalar(select(ExamEvent).where(ExamEvent.id == event_id, ExamEvent.semester_id == semester(db).id))
    if event is None:
        raise ExamError("Событие не найдено", 404)
    return event


def create_event(db: Session, data: ExamCreate) -> ExamEvent:
    event = ExamEvent(semester_id=semester(db).id, source="manual", groups=_groups(db, data.group_ids),
                      **data.model_dump(exclude={"group_ids"}))
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def patch_event(db: Session, event_id: int, data: ExamPatch) -> ExamEvent:
    event = _event(db, event_id)
    values = data.model_dump(exclude_unset=True)
    if "group_ids" in values:
        event.groups = _groups(db, values.pop("group_ids"))
    for field, value in values.items():
        if field in ("date", "start_time", "room") and getattr(event, field) != value:
            history = f"original_{field}"
            original = getattr(event, history)
            if original is None:
                original = getattr(event, field)
            setattr(event, history, None if value == original else original)
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


def cancel_event(db: Session, event_id: int, cancelled: bool) -> ExamEvent:
    event = _event(db, event_id)
    event.cancelled = cancelled
    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event_id: int) -> None:
    db.delete(_event(db, event_id))
    db.commit()


def import_history(db: Session) -> list[ExamImport]:
    return list(db.scalars(select(ExamImport).order_by(ExamImport.uploaded_at.desc(), ExamImport.id.desc())))


def student_events(db: Session, group_id: int) -> GroupExamsOut:
    group = db.get(Group, group_id)
    if group is None:
        raise ExamError("Группа не найдена", 404)
    events = list_events(db, group_id=group_id)
    current_date = today()
    items = []
    for event in events:
        changed = any(value is not None for value in
                      [event.original_date, event.original_start_time, event.original_room])
        items.append(dict(
            id=event.id, kind={"code": event.kind, "name": KIND_NAMES[event.kind]},
            date=event.date, start_time=event.start_time.strftime("%H:%M") if event.start_time else None,
            subject=event.subject, teacher=event.teacher, room=event.room, note=event.note,
            groups=[group.name for group in event.groups],
            status="cancelled" if event.cancelled else "changed" if changed else "regular",
            change={"date": event.original_date,
                    "start_time": event.original_start_time.strftime("%H:%M") if event.original_start_time else None,
                    "room": event.original_room} if changed else None,
            is_past=event.date < current_date, days_left=(event.date - current_date).days,
        ))
    return GroupExamsOut(group=group, kinds=[kind for kind in KIND_NAMES if any(e.kind == kind for e in events)], events=items)
