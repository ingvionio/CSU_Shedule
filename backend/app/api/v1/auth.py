"""Вход администратора и авторизация студента через Moodle ЧелГУ."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import AuthError, authenticate_admin, issue_student_token, refreshable_student
from app.models import User
from app.schemas.admin import LoginIn, TokenOut
from app.schemas.student import (
    MoodleLoginIn,
    StudentProfileOut,
    StudentRefreshIn,
    StudentTokenOut,
)
from app.services import moodle as moodle_service
from app.services import students as students_service
from app.services import moodle_sessions

router = APIRouter()


def profile_out(user: User) -> StudentProfileOut:
    return StudentProfileOut(
        id=user.id,
        full_name=user.full_name,
        group_id=user.group_id,
        group_name=user.group.name if user.group else None,
        moodle_username=user.moodle_username,
        moodle_auth_error=bool(user.moodle_auth_error),
    )


@router.post("/auth/moodle/login", response_model=StudentTokenOut, summary="Вход студента через Moodle ЧелГУ")
def moodle_login(
    data: MoodleLoginIn,
    request: Request,
    db: Session = Depends(get_db),
) -> StudentTokenOut:
    """Аутентификация студента через eu.iit.csu.ru и определение группы."""
    try:
        moodle_data = moodle_service.authenticate_and_detect_student(
            db=db,
            username=data.username.strip(),
            password=data.password,
        )
        user, _ = moodle_service.save_or_update_student(
            db=db,
            moodle_data=moodle_data,
            device_key=data.device_key,
            ip=request.client.host if request.client else None,
        )
    except moodle_service.MoodleError as err:
        raise HTTPException(err.status_code, str(err)) from err

    token, expires_at = issue_student_token(user)
    return StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))


@router.post("/auth/moodle/forget", summary="Завершить общую сессию на всех устройствах")
def moodle_forget(
    user_id: int = Depends(refreshable_student),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    moodle_sessions.revoke_session(db, user_id)
    return {"status": "ok"}


@router.post("/auth/student/register", deprecated=True, summary="Устаревший способ входа отключён")
def student_register() -> None:
    raise HTTPException(status.HTTP_410_GONE, "Вход по ФИО и группе отключён. Войдите через Moodle")


@router.post("/auth/student/refresh", response_model=StudentTokenOut, summary="Обновить токен действующей общей сессии")
def student_refresh(data: StudentRefreshIn, user_id: int = Depends(refreshable_student), db: Session = Depends(get_db)) -> StudentTokenOut:
    user = students_service.get_student(db, user_id)
    try:
        if data.active:
            user = moodle_sessions.record_activity(db, user)
    except moodle_service.MoodleAuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    token, expires_at = issue_student_token(user)
    return StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))


@router.post("/auth/admin/login", response_model=TokenOut, summary="Вход администратора, выдача JWT")
def admin_login(data: LoginIn) -> TokenOut:
    try:
        token, expires_at = authenticate_admin(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)
