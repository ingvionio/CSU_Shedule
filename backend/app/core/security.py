"""Авторизация: администратор (логин/пароль из настроек) и студент (профиль), JWT."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models import User

ALGORITHM = "HS256"
ROLE_ADMIN = "admin"
ROLE_STUDENT = "student"
ROLE_PRODUCT = "product"

_bearer = HTTPBearer(auto_error=False)


class AuthError(Exception):
    """Вход невозможен: неверные данные или вход не настроен."""


def issue_token(subject: str, role: str, ttl_hours: int) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    token = jwt.encode({"sub": subject, "role": role, "exp": expires_at}, get_settings().jwt_secret, algorithm=ALGORITHM)
    return token, expires_at


def _authenticate(login: str, password: str, expected_login: str, expected_password: str, role: str) -> tuple[str, datetime]:
    login_ok = secrets.compare_digest(login.encode(), expected_login.encode())
    password_ok = secrets.compare_digest(password.encode(), expected_password.encode())
    if not (login_ok and password_ok):
        raise AuthError("неверный логин или пароль")
    return issue_token(login, role, get_settings().jwt_ttl_hours)


def authenticate_admin(login: str, password: str) -> tuple[str, datetime]:
    """Проверяет логин и пароль, возвращает токен и время его истечения."""
    settings = get_settings()
    if not settings.admin_password:
        raise AuthError("вход администратора не настроен (ADMIN_PASSWORD)")
    return _authenticate(login, password, settings.admin_login, settings.admin_password, ROLE_ADMIN)


def authenticate_product(login: str, password: str) -> tuple[str, datetime]:
    """Вход в ЛК продукта (/statistic) — отдельная учётная запись, не методиста."""
    settings = get_settings()
    if not settings.product_password:
        raise AuthError("вход в ЛК продукта не настроен (PRODUCT_PASSWORD)")
    return _authenticate(login, password, settings.product_login, settings.product_password, ROLE_PRODUCT)


def _payload(credentials: HTTPAuthorizationCredentials | None, missing: str, *, verify_exp: bool = True) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, missing)

    try:
        return jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=[ALGORITHM],
                          options={"verify_exp": verify_exp, "require": ["sub", "role", "exp"]})
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия истекла, войдите снова") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "недействительный токен") from error


async def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Зависимость для админских эндпоинтов. Возвращает логин админа."""
    payload = _payload(credentials, "нужен вход администратора")
    if payload.get("role") != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет прав администратора")
    return payload["sub"]


async def _student_session(credentials: HTTPAuthorizationCredentials | None, db: AsyncSession, *, verify_exp: bool = True) -> User:
    from app.services.moodle import MoodleAuthError
    from app.services.moodle_sessions import require_session

    payload = _payload(credentials, "нужен вход через Moodle", verify_exp=verify_exp)
    if payload.get("role") != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "доступно только студенту")
    try:
        user_id = int(payload["sub"])
        sid = payload.get("sid")
        if not isinstance(sid, str):
            raise ValueError("Отсутствует серверная сессия")
        return await require_session(db, user_id, sid)
    except (KeyError, ValueError, TypeError, MoodleAuthError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия завершена, войдите через Moodle") from None


async def require_student(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> int:
    return (await _student_session(credentials, db)).id


async def refreshable_student(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> User:
    # Истечение JWT допустимо только здесь: подпись, sid и срок общей сессии проверяются всегда.
    return await _student_session(credentials, db, verify_exp=False)


def issue_student_token(user: User) -> tuple[str, datetime]:
    from app.services.moodle_sessions import session_expires_at

    expires_at = session_expires_at(user)
    token = jwt.encode({"sub": str(user.id), "role": ROLE_STUDENT, "sid": user.moodle_session_id,
                        "exp": expires_at}, get_settings().jwt_secret, algorithm=ALGORITHM)
    return token, expires_at


async def require_product(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Зависимость для эндпоинтов ЛК продукта. Возвращает логин."""
    payload = _payload(credentials, "нужен вход в ЛК продукта")
    if payload.get("role") != ROLE_PRODUCT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет доступа к ЛК продукта")
    return payload["sub"]


async def optional_student(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> int | None:
    if credentials is None:
        return None
    try:
        return (await _student_session(credentials, db)).id
    except HTTPException:
        return None
