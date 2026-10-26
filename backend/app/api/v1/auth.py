"""Вход администратора и регистрация студента."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import ROLE_STUDENT, AuthError, authenticate_admin, issue_token
from app.models import User
from app.schemas.admin import LoginIn, TokenOut
from app.schemas.student import StudentProfileOut, StudentRegisterIn, StudentTokenOut
from app.services import students as students_service

router = APIRouter()


def profile_out(user: User) -> StudentProfileOut:
    return StudentProfileOut(
        id=user.id,
        full_name=user.full_name,
        group_id=user.group_id,
        group_name=user.group.name if user.group else None,
    )


@router.post("/auth/student/register", response_model=StudentTokenOut, summary="Профиль студента: ФИО и группа")
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
