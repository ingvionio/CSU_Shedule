"""Авторизация администратора: логин/пароль из настроек и JWT."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

ALGORITHM = "HS256"
ROLE_ADMIN = "admin"

_bearer = HTTPBearer(auto_error=False)


class AuthError(Exception):
    """Вход невозможен: неверные данные или вход не настроен."""


def authenticate_admin(login: str, password: str) -> tuple[str, datetime]:
    """Проверяет логин и пароль, возвращает токен и время его истечения."""
    settings = get_settings()
    if not settings.admin_password:
        raise AuthError("вход администратора не настроен (ADMIN_PASSWORD)")

    login_ok = secrets.compare_digest(login.encode(), settings.admin_login.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    if not (login_ok and password_ok):
        raise AuthError("неверный логин или пароль")

    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    token = jwt.encode(
        {"sub": login, "role": ROLE_ADMIN, "exp": expires_at},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    return token, expires_at


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Зависимость для админских эндпоинтов. Возвращает логин админа."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен вход администратора")

    try:
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия истекла, войдите снова") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "недействительный токен") from error

    if payload.get("role") != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет прав администратора")
    return payload["sub"]
