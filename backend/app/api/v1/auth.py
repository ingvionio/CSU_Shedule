"""Вход администратора и авторизация студента через Moodle ЧелГУ."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.rate_limit import limit_login
from app.core.security import (
    AdminSession, AuthError, admin_session, authenticate_admin, authenticate_product, issue_student_token,
    refreshable_student, revoke_admin_sessions,
)
from app.models import User
from app.schemas.admin import LoginIn, TokenOut
from app.schemas.student import (
    MoodleLoginIn,
    StudentProfileOut,
    StudentRefreshIn,
    StudentTokenOut,
)
from app.services import moodle as moodle_service
from app.services import moodle_sessions, product_events

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
async def moodle_login(
    data: MoodleLoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> StudentTokenOut:
    """Аутентификация студента через eu.iit.csu.ru и определение группы."""
    await limit_login(db, request, "moodle", data.username)
    client = {
        "device_key": data.device_key,
        "platform": request.headers.get("X-Client-Platform"),
        "app_version": request.headers.get("X-Client-Version"),
    }
    try:
        moodle_data = await moodle_service.authenticate_and_detect_student(
            db=db,
            username=data.username.strip(),
            password=data.password,
        )
        user, _ = await moodle_service.save_or_update_student(
            db=db,
            moodle_data=moodle_data,
            device_key=data.device_key,
            ip=request.client.host if request.client else None,
        )
    except moodle_service.MoodleError as err:
        await db.rollback()
        await product_events.record_server_event(db, _login_failure_event(err), user_id=None, **client)
        raise HTTPException(err.status_code, str(err)) from err

    token, expires_at = issue_student_token(user)
    response = StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))
    await product_events.record_server_event(db, product_events.LOGIN_SUCCESS, user_id=user.id, **client)
    return response


def _login_failure_event(error: moodle_service.MoodleError) -> str:
    if isinstance(error, moodle_service.MoodleAuthError):
        return product_events.LOGIN_FAILED_AUTH
    if isinstance(error, moodle_service.MoodleGroupError):
        return product_events.LOGIN_FAILED_GROUP
    return product_events.LOGIN_FAILED_OTHER


@router.post("/auth/moodle/forget", summary="Завершить общую сессию на всех устройствах")
async def moodle_forget(
    user: User = Depends(refreshable_student),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, str]:
    await moodle_sessions.revoke_session(db, user.id, user.moodle_session_id)
    return {"status": "ok"}


@router.post("/auth/student/register", deprecated=True, summary="Устаревший способ входа отключён")
async def student_register() -> None:
    raise HTTPException(status.HTTP_410_GONE, "Вход по ФИО и группе отключён. Войдите через Moodle")


@router.post("/auth/student/refresh", response_model=StudentTokenOut, summary="Обновить токен действующей общей сессии")
async def student_refresh(
    data: StudentRefreshIn,
    user: User = Depends(refreshable_student),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> StudentTokenOut:
    try:
        if data.active:
            user = await moodle_sessions.record_activity(db, user)
    except moodle_service.MoodleAuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    token, expires_at = issue_student_token(user)
    return StudentTokenOut(access_token=token, expires_at=expires_at, profile=profile_out(user))


@router.post("/auth/admin/login", response_model=TokenOut, summary="Вход администратора, выдача JWT")
async def admin_login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db, scope="function")) -> TokenOut:
    await limit_login(db, request, "admin", data.login)
    try:
        token, expires_at = authenticate_admin(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)


@router.post("/auth/admin/logout", status_code=204, summary="Отозвать текущую сессию администратора")
async def admin_logout(
    session: AdminSession = Depends(admin_session, scope="function"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> None:
    await revoke_admin_sessions(db, session)


@router.post("/auth/product/login", response_model=TokenOut, summary="Вход в ЛК продукта (/statistic), выдача JWT")
async def product_login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db, scope="function")) -> TokenOut:
    await limit_login(db, request, "product", data.login)
    try:
        token, expires_at = authenticate_product(data.login, data.password)
    except AuthError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error
    return TokenOut(access_token=token, expires_at=expires_at)
