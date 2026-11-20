from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import User


class StudentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_student(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise StudentError("профиль не найден, войдите через Moodle", 401)
    return user
