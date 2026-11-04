"""Групповая домашка: просмотр студентами, редакторы группы и аудит."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.me import current_student
from app.core.db import get_db
from app.core.security import require_admin
from app.models import GroupHomework, HomeworkCompletion, User
from app.schemas.homework import EditorIn, EditorOut, HomeworkIn, HomeworkListOut, HomeworkOut, HomeworkPatch
from app.services import homework as homework_service

router = APIRouter(prefix="/me/homework")
admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _raise(error: homework_service.HomeworkError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


def _out(db: Session, item: GroupHomework, user_id: int) -> HomeworkOut:
    completed = db.scalar(select(HomeworkCompletion.id).where(
        HomeworkCompletion.homework_id == item.id, HomeworkCompletion.user_id == user_id
    )) is not None
    return HomeworkOut(
        id=item.id,
        group_id=item.group_id,
        group_name=item.group.name,
        lesson_id=item.lesson_id,
        lesson_date=item.lesson_date,
        subject=item.subject.name if item.subject else None,
        title=item.title,
        body=item.body,
        due_date=item.due_date,
        source=item.source,
        status=item.status,
        version=item.version,
        created_by=item.created_by,
        created_by_name=item.creator.full_name,
        updated_by=item.updated_by,
        updated_by_name=item.updater.full_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_by_me=completed,
    )


@router.get("", response_model=HomeworkListOut, summary="Домашка своей группы")
def list_my_homework(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    user: User = Depends(current_student),
    db: Session = Depends(get_db),
) -> HomeworkListOut:
    if start and end and end < start:
        raise HTTPException(422, "end не может быть раньше start")
    try:
        can_edit, items = homework_service.list_homework(db, user, user.group_id or 0, start, end)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
    return HomeworkListOut(can_edit=can_edit, items=[_out(db, item, user.id) for item in items])


@router.post("", response_model=HomeworkOut, status_code=status.HTTP_201_CREATED, summary="Добавить домашку группы")
def create_my_homework(data: HomeworkIn, user: User = Depends(current_student), db: Session = Depends(get_db)) -> HomeworkOut:
    try:
        item = homework_service.create(db, user, user.group_id or 0, data)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
    return _out(db, item, user.id)


@router.patch("/{homework_id}", response_model=HomeworkOut, summary="Изменить домашку группы")
def update_my_homework(
    homework_id: int, data: HomeworkPatch, user: User = Depends(current_student), db: Session = Depends(get_db)
) -> HomeworkOut:
    try:
        item = homework_service.update_homework(db, user, homework_id, data)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
    return _out(db, item, user.id)


@router.post("/{homework_id}/complete", response_model=HomeworkOut, summary="Отметить домашку выполненной для себя")
def complete_my_homework(
    homework_id: int,
    completed: bool = Query(default=True),
    user: User = Depends(current_student),
    db: Session = Depends(get_db),
) -> HomeworkOut:
    try:
        homework_service.complete(db, user, homework_id, completed)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
    item = db.get(GroupHomework, homework_id)
    return _out(db, item, user.id)


@admin_router.get("/groups/{group_id}/editors", response_model=list[EditorOut], summary="Редакторы домашки группы")
def list_editors(group_id: int, db: Session = Depends(get_db)) -> list[EditorOut]:
    return [EditorOut(user_id=item.user_id, full_name=item.user.full_name, group_id=item.group_id, is_primary=item.is_primary, active=item.active)
            for item in homework_service.editors(db, group_id) if item.active]


@admin_router.post("/groups/{group_id}/editors", response_model=EditorOut, summary="Назначить редактора домашки")
def assign_editor(group_id: int, data: EditorIn, db: Session = Depends(get_db)) -> EditorOut:
    try:
        item = homework_service.assign_editor(db, group_id, data)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
    return EditorOut(user_id=item.user_id, full_name=item.user.full_name, group_id=item.group_id, is_primary=item.is_primary, active=item.active)


@admin_router.delete("/groups/{group_id}/editors/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Отозвать редактора")
def remove_editor(group_id: int, user_id: int, db: Session = Depends(get_db)) -> None:
    try:
        homework_service.remove_editor(db, group_id, user_id)
    except homework_service.HomeworkError as error:
        raise _raise(error) from error
