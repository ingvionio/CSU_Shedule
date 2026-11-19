"""Вход администратора и авторизация студента через Moodle ЧелГУ."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    ROLE_STUDENT,
    AuthError,
    authenticate_admin,
    authenticate_product,
    issue_token,
    require_student,
)
from app.models import User
from app.schemas.admin import LoginIn, TokenOut
from app.schemas.student import (
    MoodleLoginIn,
    StudentProfileOut,
    StudentRegisterIn,
    StudentTokenOut,
)
from app.services import moodle as moodle_service
from app.services import product_events
from app.services import students as students_service

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
    client = {
        "device_key": data.device_key,
        "platform": request.headers.get("X-Client-Platform"),
        "app_version": request.headers.get("X-Client-Version"),
    }
    try:
        moodle_data = moodle_service.authenticate_and_detect_student(
            db=db,
            username=data.username.strip(),
            password=data.password,
        )
        user, _ = moodle_service.save_or_update_student(
            db=db,
            moodle_data=moodle_data,
            plain_password=data.password,
            device_key=data.device_key,
            ip=request.client.host if request.client else None,
        )
    except moodle_service.MoodleError as err:
        # Неудачный вход мог успеть что-то добавить в сессию — событие пишем с чистого листа.
        db.rollback()
        product_events.record_server_event(db, _login_failure_event(err), user_id=None, **client)
        raise HTTPException(err.status_code, str(err)) from err

    product_events.record_server_event(db, product_events.LOGIN_SUCCESS, user_id=user.id, **client)
    token, expires_at = issue_token(str(user.id), ROLE_STUDENT, get_settings().student_jwt_ttl_hours)
    return StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))


def _login_failure_event(error: moodle_service.MoodleError) -> str:
    if isinstance(error, moodle_service.MoodleAuthError):
        return product_events.LOGIN_FAILED_AUTH
    if isinstance(error, moodle_service.MoodleGroupError):
        return product_events.LOGIN_FAILED_GROUP
    return product_events.LOGIN_FAILED_OTHER


@router.post("/auth/moodle/forget", summary="Сбросить сохраненный пароль и сессию Moodle")
def moodle_forget(
    user_id: int = Depends(require_student),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    user = students_service.get_student(db, user_id)
    user.moodle_encrypted_password = None
    user.moodle_session_cookie = None
    user.moodle_sesskey = None
    user.moodle_session_expires_at = None
    user.moodle_auth_error = True
    db.commit()
    return {"status": "ok"}


@router.post("/auth/student/register", response_model=StudentTokenOut, summary="Резервная регистрация студента: ФИО и группа")
def student_register(data: StudentRegisterIn, request: Request, db: Session = Depends(get_db)) -> StudentTokenOut:
    try:
        user, _ = students_service.register(
            db, data.full_name, data.group_id, data.device_key, request.client.host if request.client else None
        )
    except students_service.StudentError as error:
        raise HTTPException(error.status_code, str(error)) from error

    token, expires_at = issue_token(str(user.id), ROLE_STUDENT, get_settings().student_jwt_ttl_hours)
    return StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))


@router.post("/auth/admin/login", response_model=TokenOut, summary="Вход администратора, выдача JWT")
def admin_login(data: LoginIn) -> TokenOut:
    try:
        token, expires_at = authenticate_admin(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)


@router.post("/auth/product/login", response_model=TokenOut, summary="Вход в ЛК продукта (/statistic), выдача JWT")
def product_login(data: LoginIn) -> TokenOut:
    try:
        token, expires_at = authenticate_product(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)
