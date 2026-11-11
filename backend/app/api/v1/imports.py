"""Админская загрузка расписания и история импортов."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import require_admin
from app.schemas.imports import ImportHistoryOut, SemesterImportOut, WeeklyImportOut
from app.services import admin_imports

router = APIRouter(prefix="/admin/imports", dependencies=[Depends(require_admin)])


@router.post("/weekly", response_model=WeeklyImportOut, summary="Проверить или загрузить понедельное расписание")
def weekly(
    files: list[UploadFile] | None = File(default=None),
    dry_run: bool = Form(default=True),
    skip_errors: bool = Form(default=False),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> WeeklyImportOut:
    try:
        return admin_imports.upload_weekly(db, files or [], dry_run, skip_errors, admin)
    except admin_imports.UploadError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.post("/semester", response_model=SemesterImportOut, summary="Проверить или загрузить расписание семестра")
def semester(
    file: UploadFile | None = File(default=None),
    dry_run: bool = Form(default=True),
    db: Session = Depends(get_db),
    admin: str = Depends(require_admin),
) -> SemesterImportOut:
    try:
        return admin_imports.upload_semester(db, [file] if file else [], dry_run, admin)
    except admin_imports.UploadError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.get("", response_model=list[ImportHistoryOut], summary="Последние загрузки расписания")
def history(limit: int = Query(default=20, ge=1), db: Session = Depends(get_db)) -> list[ImportHistoryOut]:
    return admin_imports.import_history(db, limit)
