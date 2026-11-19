"""Авторизация: администратор (логин/пароль из настроек) и студент (профиль), JWT."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

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


def _payload(credentials: HTTPAuthorizationCredentials | None, missing: str) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, missing)

    try:
        return jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия истекла, войдите снова") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "недействительный токен") from error


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Зависимость для админских эндпоинтов. Возвращает логин админа."""
    payload = _payload(credentials, "нужен вход администратора")
    if payload.get("role") != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет прав администратора")
    return payload["sub"]


def require_student(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> int:
    """Зависимость для эндпоинтов /me. Возвращает id студента."""
    payload = _payload(credentials, "нужен профиль студента")
    if payload.get("role") != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "доступно только студенту")
    return int(payload["sub"])


def require_product(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Зависимость для эндпоинтов ЛК продукта. Возвращает логин."""
    payload = _payload(credentials, "нужен вход в ЛК продукта")
    if payload.get("role") != ROLE_PRODUCT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет доступа к ЛК продукта")
    return payload["sub"]


def optional_student(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> int | None:
    """id студента, если передан его действующий токен; иначе None, без ошибки."""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    if payload.get("role") != ROLE_STUDENT:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
