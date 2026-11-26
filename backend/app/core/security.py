"""Авторизация: администратор (логин/пароль из настроек) и студент (профиль), JWT."""

from __future__ import annotations

import secrets
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from jwt.utils import base64url_decode
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models import AdminRevocation, User

ALGORITHM = "HS256"
ROLE_ADMIN = "admin"
ROLE_STUDENT = "student"
ROLE_PRODUCT = "product"

_bearer = HTTPBearer(auto_error=False)


class AuthError(Exception):
    """Вход невозможен: неверные данные или вход не настроен."""


def issue_token(subject: str, role: str, ttl_hours: int) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)
    claims = {"sub": subject, "role": role, "exp": expires_at}
    if role == ROLE_ADMIN:
        claims.update(iat=int(now.timestamp()), jti=secrets.token_hex(16))
    token = jwt.encode(claims, get_settings().jwt_secret, algorithm=ALGORITHM)
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


@dataclass(frozen=True)
class AdminSession:
    login: str
    key: str
    expires_at: int


async def admin_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> AdminSession:
    payload = _payload(credentials, "нужен вход администратора")
    if payload.get("role") != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "нет прав администратора")
    assert credentials is not None
    signature = credentials.credentials.rsplit(".", 1)[-1]
    key = sha256(base64url_decode(signature.encode("ascii"))).hexdigest()
    revocations = dict((await db.execute(select(AdminRevocation.key, AdminRevocation.revoked_at).where(
        AdminRevocation.key.in_((key, "all")),
    ))).tuples().all())
    issued_at = int(payload.get("iat", 0))
    if key in revocations or issued_at <= revocations.get("all", -1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "сессия администратора завершена")
    return AdminSession(payload["sub"], key, int(payload["exp"]))


async def require_admin(session: AdminSession = Depends(admin_session, scope="function")) -> str:
    return session.login


async def revoke_admin_sessions(db: AsyncSession, session: AdminSession | None = None) -> None:
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(AdminRevocation).values(
        key=session.key if session else "all",
        revoked_at=int(datetime.now(timezone.utc).timestamp()),
        expires_at=session.expires_at if session else None,
    )
    if session:
        statement = statement.on_conflict_do_nothing(index_elements=[AdminRevocation.key])
    else:
        statement = statement.on_conflict_do_update(
            index_elements=[AdminRevocation.key], set_={"revoked_at": statement.excluded.revoked_at},
            where=AdminRevocation.revoked_at < statement.excluded.revoked_at,
        )
    await db.execute(statement)
    await db.commit()


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


async def require_student_profile(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> User:
    return await _student_session(credentials, db)


async def require_student(
    student: User = Depends(require_student_profile),
) -> int:
    return student.id


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
