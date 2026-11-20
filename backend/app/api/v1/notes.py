"""All note queries are scoped to the authenticated student, including mutations."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import current_student
from app.core.db import get_db
from app.models import Group, PersonalNote, User
from app.services import product_events, schedule

router = APIRouter(prefix="/me/notes")


class NoteIn(BaseModel):
    group_id: int
    lesson_date: date
    lesson_ref: str = Field(pattern=r"^[lo]-[1-9][0-9]*$")
    body: str = Field(min_length=1, max_length=5000)
    version: int = Field(default=0, ge=0)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Введите текст заметки")
        return value.strip()


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    occurrence_key: str
    group_id: int
    lesson_date: date
    subject: str
    body: str
    version: int
    updated_at: datetime


@router.get("", response_model=list[NoteOut])
async def list_notes(user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")):
    return list(await db.scalars(select(PersonalNote).where(PersonalNote.user_id == user.id).order_by(PersonalNote.lesson_date.desc(), PersonalNote.id.desc())))


@router.post("", response_model=NoteOut)
async def save_note(data: NoteIn, user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")):
    group = await db.get(Group, data.group_id)
    if group is None:
        raise HTTPException(404, "Группа не найдена")
    try:
        semester = await schedule.active_semester(db)
        day = await schedule.build_day(db, group, semester, data.lesson_date, data.lesson_date)
    except schedule.ScheduleError as error:
        raise HTTPException(422, "Дата вне расписания") from error
    lesson = next((item for item in day["lessons"] if item["id"] == data.lesson_ref), None)
    if lesson is None:
        raise HTTPException(409, "Расписание изменилось. Откройте пару заново")
    key = lesson["note_key"]
    item = await db.scalar(select(PersonalNote).where(PersonalNote.user_id == user.id, PersonalNote.occurrence_key == key))
    if item is None:
        if data.version != 0:
            raise HTTPException(409, "Заметка удалена. Обновите страницу")
        item = PersonalNote(user_id=user.id, occurrence_key=key, group_id=group.id,
                            lesson_date=data.lesson_date, subject=lesson["subject"], body=data.body, version=1)
        db.add(item)
    else:
        result = await db.execute(update(PersonalNote).where(PersonalNote.id == item.id, PersonalNote.user_id == user.id,
                            PersonalNote.version == data.version).values(body=data.body, version=data.version + 1))
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(409, "Заметка изменена в другой вкладке. Обновите её перед сохранением")
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "Заметка уже создана. Обновите страницу") from error
    await db.refresh(item)
    response = NoteOut.model_validate(item)
    await product_events.record_server_event(db, product_events.NOTE_SAVED, user_id=user.id)
    return response


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, version: int = Query(ge=1), user: User = Depends(current_student), db: AsyncSession = Depends(get_db, scope="function")):
    item = await db.scalar(select(PersonalNote).where(PersonalNote.id == note_id, PersonalNote.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Заметка не найдена")
    result = await db.execute(delete(PersonalNote).where(PersonalNote.id == note_id, PersonalNote.user_id == user.id, PersonalNote.version == version))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, "Заметка изменилась. Обновите страницу")
    await db.commit()
