from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import Group, GroupEditor, GroupHomework, HomeworkCompletion, HomeworkRevision, Lesson, Subject, User
from app.schemas.homework import EditorIn, HomeworkIn, HomeworkPatch


class HomeworkError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def is_editor(db: Session, user_id: int, group_id: int) -> bool:
    return db.scalar(select(GroupEditor.id).where(
        GroupEditor.user_id == user_id, GroupEditor.group_id == group_id, GroupEditor.active.is_(True)
    )) is not None


def editors(db: Session, group_id: int) -> list[GroupEditor]:
    return list(db.scalars(select(GroupEditor).where(GroupEditor.group_id == group_id).order_by(GroupEditor.is_primary.desc(), GroupEditor.id)).unique())


def list_homework(db: Session, user: User, group_id: int, start: date | None, end: date | None) -> tuple[bool, list[GroupHomework]]:
    if user.group_id != group_id:
        raise HomeworkError("домашка доступна только для своей группы", 403)
    query = select(GroupHomework).where(GroupHomework.group_id == group_id, GroupHomework.status != "archived")
    if start is not None:
        query = query.where(GroupHomework.lesson_date >= start)
    if end is not None:
        query = query.where(GroupHomework.lesson_date <= end)
    query = query.order_by(GroupHomework.due_date.is_(None), GroupHomework.due_date, GroupHomework.lesson_date, GroupHomework.id)
    return is_editor(db, user.id, group_id), list(db.scalars(query).unique())


def _subject(db: Session, name: str | None, lesson: Lesson | None) -> Subject | None:
    value = (name or (lesson.subject.name if lesson else "")).strip()
    if not value:
        return None
    found = db.scalar(select(Subject).where(Subject.name == value))
    if found:
        return found
    found = Subject(name=value)
    db.add(found)
    db.flush()
    return found


def _lesson(db: Session, group_id: int, lesson_id: int | None) -> Lesson | None:
    if lesson_id is None:
        return None
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.group_id != group_id:
        raise HomeworkError("пара не найдена в этой группе", 422)
    return lesson


def _snapshot(item: GroupHomework) -> dict:
    return {"title": item.title, "body": item.body, "due_date": item.due_date, "source": item.source, "status": item.status}


def _audit(db: Session, item: GroupHomework, user_id: int) -> None:
    data = _snapshot(item)
    db.add(HomeworkRevision(homework_id=item.id, version=item.version, user_id=user_id, **data))


def create(db: Session, user: User, group_id: int, data: HomeworkIn) -> GroupHomework:
    if user.group_id != group_id or not is_editor(db, user.id, group_id):
        raise HomeworkError("нет прав редактора этой группы", 403)
    lesson = _lesson(db, group_id, data.lesson_id)
    item = GroupHomework(
        group_id=group_id, lesson_id=lesson.id if lesson else None, lesson_date=data.lesson_date,
        subject=_subject(db, data.subject, lesson), title=data.title.strip(), body=data.body.strip(),
        due_date=data.due_date, source=data.source, status="published", created_by=user.id, updated_by=user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, item, user.id)
    db.commit()
    db.refresh(item)
    return item


def update_homework(db: Session, user: User, item_id: int, data: HomeworkPatch) -> GroupHomework:
    item = db.get(GroupHomework, item_id)
    if item is None:
        raise HomeworkError("домашка не найдена", 404)
    if user.group_id != item.group_id or not is_editor(db, user.id, item.group_id):
        raise HomeworkError("нет прав редактора этой группы", 403)
    if item.version != data.version:
        raise HomeworkError("домашка уже изменена другим редактором; обновите страницу", 409)
    lesson = _lesson(db, item.group_id, data.lesson_id) if data.lesson_id is not None else item.lesson
    values = data.model_dump(exclude_unset=True, exclude={"version", "subject"})
    for key, value in values.items():
        if key == "title" and value is not None:
            value = value.strip()
        if key == "body" and value is not None:
            value = value.strip()
        setattr(item, key, value)
    if "lesson_id" in values:
        item.lesson_id = lesson.id if lesson else None
    if "subject" in data.model_fields_set:
        item.subject = _subject(db, data.subject, lesson)
    item.version += 1
    item.updated_by = user.id
    item.updated_at = datetime.now(timezone.utc)
    db.flush()
    _audit(db, item, user.id)
    db.commit()
    db.refresh(item)
    return item


def complete(db: Session, user: User, item_id: int, completed: bool) -> None:
    item = db.get(GroupHomework, item_id)
    if item is None or item.group_id != user.group_id or item.status == "archived":
        raise HomeworkError("домашка не найдена", 404)
    if completed:
        existing = db.scalar(select(HomeworkCompletion).where(
            HomeworkCompletion.homework_id == item_id, HomeworkCompletion.user_id == user.id
        ))
        if existing is None:
            db.add(HomeworkCompletion(homework_id=item_id, user_id=user.id))
    else:
        db.execute(delete(HomeworkCompletion).where(HomeworkCompletion.homework_id == item_id, HomeworkCompletion.user_id == user.id))
    db.commit()


def assign_editor(db: Session, group_id: int, data: EditorIn) -> GroupEditor:
    user = db.get(User, data.user_id)
    if user is None or user.group_id != group_id:
        raise HomeworkError("студент не состоит в этой группе", 422)
    existing = db.scalar(select(GroupEditor).where(GroupEditor.group_id == group_id, GroupEditor.user_id == data.user_id))
    if existing:
        existing.active = True
        existing.is_primary = data.is_primary
        editor = existing
    else:
        active_count = db.scalar(select(func.count(GroupEditor.id)).where(GroupEditor.group_id == group_id, GroupEditor.active.is_(True))) or 0
        if active_count >= 3:
            raise HomeworkError("у группы может быть не больше трёх активных редакторов", 422)
        editor = GroupEditor(group_id=group_id, user_id=data.user_id, is_primary=data.is_primary, active=True)
        db.add(editor)
    if data.is_primary:
        db.execute(update(GroupEditor).where(GroupEditor.group_id == group_id, GroupEditor.user_id != data.user_id).values(is_primary=False))
    db.commit()
    db.refresh(editor)
    return editor


def remove_editor(db: Session, group_id: int, user_id: int) -> None:
    editor = db.scalar(select(GroupEditor).where(GroupEditor.group_id == group_id, GroupEditor.user_id == user_id))
    if editor is None:
        raise HomeworkError("редактор не найден", 404)
    editor.active = False
    editor.is_primary = False
    db.commit()
