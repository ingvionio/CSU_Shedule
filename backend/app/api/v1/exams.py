"""API сессии: публичный список и инструменты методиста."""
from collections.abc import Callable
from typing import TypeVar
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin
from app.schemas.exam import ExamCreate, ExamEventOut, ExamImportHistoryOut, ExamImportOut, ExamKind, ExamPatch, GroupExamsOut
from app.services import exams
from app.services.exam_importer import import_workbook

router = APIRouter()
admin_router = APIRouter(prefix="/admin/exams", dependencies=[Depends(require_admin)])
T = TypeVar("T")


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except exams.ExamError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.get("/groups/{group_id}/exams", response_model=GroupExamsOut)
def group_exams(group_id: int, db: Session = Depends(get_db)) -> GroupExamsOut:
    return _call(lambda: exams.student_events(db, group_id))


@admin_router.post("/import", response_model=ExamImportOut)
def upload_exams(kind: ExamKind, apply: bool = False, file: UploadFile = File(...),
                 db: Session = Depends(get_db), admin: str = Depends(require_admin)) -> ExamImportOut:
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(400, "Выберите файл .xlsx")
    if len(name) > 300:
        raise HTTPException(400, "Имя файла длиннее 300 символов")
    payload = file.file.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(413, "Файл превышает допустимый размер (20 МБ)")
    current = _call(lambda: exams.semester(db))
    try:
        return import_workbook(db, payload, current, kind, name, admin, apply=apply)
    except (ValueError, KeyError, OSError, BadZipFile, ParseError, InvalidFileException) as error:
        raise HTTPException(400, "Не удалось прочитать книгу Excel") from error


@admin_router.get("/imports", response_model=list[ExamImportHistoryOut])
def history(db: Session = Depends(get_db)) -> list:
    return exams.import_history(db)


@admin_router.get("", response_model=list[ExamEventOut])
def events(kind: ExamKind | None = None, group_id: int | None = None,
           course: int | None = Query(None, ge=1, le=6), db: Session = Depends(get_db)) -> list:
    return _call(lambda: exams.list_events(db, kind, group_id, course))


@admin_router.post("", response_model=ExamEventOut, status_code=201)
def create(data: ExamCreate, db: Session = Depends(get_db)) -> object:
    return _call(lambda: exams.create_event(db, data))


@admin_router.patch("/{event_id}", response_model=ExamEventOut)
def patch(event_id: int, data: ExamPatch, db: Session = Depends(get_db)) -> object:
    return _call(lambda: exams.patch_event(db, event_id, data))


@admin_router.post("/{event_id}/cancel", response_model=ExamEventOut)
def cancel(event_id: int, db: Session = Depends(get_db)) -> object:
    return _call(lambda: exams.cancel_event(db, event_id, True))


@admin_router.post("/{event_id}/restore", response_model=ExamEventOut)
def restore(event_id: int, db: Session = Depends(get_db)) -> object:
    return _call(lambda: exams.cancel_event(db, event_id, False))


@admin_router.delete("/{event_id}", status_code=204)
def remove(event_id: int, db: Session = Depends(get_db)) -> Response:
    _call(lambda: exams.delete_event(db, event_id))
    return Response(status_code=204)
