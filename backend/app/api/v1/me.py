"""Эндпоинты студента с профилем: /me. Требуют студенческий токен."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import profile_out
from app.core.db import get_db
from app.core.security import require_student
from app.models import User
from app.schemas.student import MeOut
from app.services import messages as messages_service
from app.services import students as students_service

router = APIRouter(prefix="/me")


def current_student(user_id: int = Depends(require_student), db: Session = Depends(get_db)) -> User:
    try:
        return students_service.get_student(db, user_id)
    except students_service.StudentError as error:
        raise HTTPException(error.status_code, str(error)) from error


@router.get("", response_model=MeOut, summary="Профиль и число непрочитанных")
def me(user: User = Depends(current_student), db: Session = Depends(get_db)) -> MeOut:
    return MeOut(**profile_out(user).model_dump(), unread_count=messages_service.unread_count(db, user.id))
