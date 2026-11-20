"""Общая сессия студента, её отзыв и фоновое продление Moodle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import secrets
from threading import Event, Thread

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.db import SessionLocal
from app.models import User
from app.services.moodle import MoodleAuthError, MoodleClient, MoodleError, MoodleSessionData

logger = logging.getLogger(__name__)
IDLE_TTL = timedelta(days=5)
POLL_SECONDS = 5


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def session_expires_at(user: User) -> datetime:
    if not user.session_last_active_at:
        raise MoodleAuthError("Сессия завершена, войдите снова")
    return as_utc(user.session_last_active_at) + IDLE_TTL


def session_active(user: User, now: datetime) -> bool:
    return bool(user.moodle_session_id and user.session_last_active_at
                and user.moodle_encrypted_cookies and user.moodle_encrypted_sesskey
                and not user.moodle_auth_error and session_expires_at(user) > now)


def refresh_interval(seconds: int) -> timedelta:
    return timedelta(seconds=max(1, min(seconds / 2, 3600)))


def start_session(user: User, data: MoodleSessionData, now: datetime) -> None:
    if not data.cookies or not data.sesskey or data.timeout_seconds <= 0:
        raise MoodleError("Не удалось получить полноценную сессию Moodle", 502)
    # Повторный вход на другом устройстве сохраняет общую действующую сессию приложения.
    if not session_active(user, now):
        user.moodle_session_id = secrets.token_hex(32)
    user.moodle_encrypted_cookies = encrypt_secret(json.dumps(data.cookies), f"user:{user.id}:cookies")
    user.moodle_encrypted_sesskey = encrypt_secret(data.sesskey, f"user:{user.id}:sesskey")
    user.session_last_active_at = now
    user.moodle_timeout_seconds = data.timeout_seconds
    user.moodle_session_expires_at = data.expires_at
    user.moodle_refresh_at = now + refresh_interval(data.timeout_seconds)
    user.moodle_auth_error = False


def _revoked_values() -> dict[str, object]:
    return {
        "moodle_session_id": None, "moodle_encrypted_cookies": None, "moodle_encrypted_sesskey": None,
        "session_last_active_at": None, "moodle_refresh_at": None, "moodle_session_expires_at": None,
        "moodle_timeout_seconds": None, "moodle_auth_error": True,
    }


def revoke_session(db: Session, user_id: int) -> None:
    db.execute(update(User).where(User.id == user_id).values(**_revoked_values()).execution_options(synchronize_session=False))
    db.commit()


def require_session(db: Session, user_id: int, session_id: str, now: datetime | None = None) -> User:
    now = now or datetime.now(timezone.utc)
    user = db.get(User, user_id)
    if user is None or not session_id or not user.moodle_session_id or not secrets.compare_digest(user.moodle_session_id, session_id):
        raise MoodleAuthError("Сессия завершена, войдите снова")
    if not session_active(user, now):
        db.execute(update(User).where(
            User.id == user.id, User.moodle_session_id == session_id,
            or_(User.session_last_active_at <= now - IDLE_TTL, User.session_last_active_at.is_(None),
                User.moodle_auth_error.is_(True), User.moodle_encrypted_cookies.is_(None), User.moodle_encrypted_sesskey.is_(None)),
        ).values(**_revoked_values()).execution_options(synchronize_session=False))
        db.commit()
        raise MoodleAuthError("Сессия истекла, войдите снова")
    return user


def record_activity(db: Session, user: User, now: datetime | None = None) -> User:
    now = now or datetime.now(timezone.utc)
    result = db.execute(update(User).where(
        User.id == user.id, User.moodle_session_id == user.moodle_session_id,
        User.session_last_active_at > now - IDLE_TTL,
    ).values(session_last_active_at=now, last_seen_at=now).execution_options(synchronize_session=False))
    db.commit()
    if not result.rowcount:
        raise MoodleAuthError("Сессия завершена, войдите снова")
    db.refresh(user)
    return user


def cleanup_expired(db: Session, now: datetime) -> int:
    result = db.execute(update(User).where(
        User.moodle_session_id.is_not(None),
        or_(User.session_last_active_at.is_(None), User.session_last_active_at <= now - IDLE_TTL),
    ).values(**_revoked_values()).execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount


def _refresh_one(user_id: int, now: datetime) -> None:
    with SessionLocal() as db:
        # Атомарная аренда защищает от одинаковых touch в нескольких процессах API.
        claimed = db.execute(update(User).where(
            User.id == user_id, User.moodle_refresh_at <= now,
            User.moodle_session_id.is_not(None), User.session_last_active_at > now - IDLE_TTL,
        ).values(moodle_refresh_at=now + timedelta(minutes=1)).execution_options(synchronize_session=False))
        db.commit()
        if not claimed.rowcount:
            return
        user = db.get(User, user_id)
        if user is None or not session_active(user, now):
            return
        session_id, encrypted_cookies = user.moodle_session_id, user.moodle_encrypted_cookies
        encrypted_sesskey, timeout_seconds = user.moodle_encrypted_sesskey, user.moodle_timeout_seconds

    # Сетевой запрос не держит транзакцию и блокировку строки.
    client = MoodleClient()
    try:
        cookies = json.loads(decrypt_secret(encrypted_cookies, f"user:{user_id}:cookies"))
        sesskey = decrypt_secret(encrypted_sesskey, f"user:{user_id}:sesskey")
        if not isinstance(cookies, dict) or not cookies or not all(isinstance(k, str) and isinstance(v, str) for k, v in cookies.items()):
            raise ValueError("Некорректные cookies")
        client.session.cookies.update(cookies)
        seconds = timeout_seconds if get_settings().moodle_mock else client.touch_session(sesskey)
        if type(seconds) is not int or seconds <= 0:
            raise MoodleError("Не удалось определить срок сессии Moodle", 502)
        values = {
            "moodle_encrypted_cookies": encrypt_secret(json.dumps(client.session.cookies.get_dict()), f"user:{user_id}:cookies"),
            "moodle_session_expires_at": now + timedelta(seconds=seconds),
            "moodle_timeout_seconds": seconds, "moodle_refresh_at": now + refresh_interval(seconds),
        }
    except (ValueError, MoodleAuthError):
        values = _revoked_values()
    except MoodleError:
        values = {"moodle_refresh_at": now + timedelta(seconds=min(60, max(1, (timeout_seconds or 120) / 4)))}
        logger.warning("Временная ошибка продления Moodle-сессии пользователя %s", user_id)
    finally:
        client.session.close()

    with SessionLocal() as db:
        # Старый ответ не перезаписывает повторный вход и не восстанавливает отозванную сессию.
        db.execute(update(User).where(
            User.id == user_id, User.moodle_session_id == session_id,
            User.moodle_encrypted_cookies == encrypted_cookies,
            User.session_last_active_at > now - IDLE_TTL,
        ).values(**values).execution_options(synchronize_session=False))
        db.commit()


def maintain_sessions(now: datetime | None = None, stop: Event | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    with SessionLocal() as db:
        cleanup_expired(db, now)
        due = list(db.scalars(select(User.id).where(
            User.moodle_session_id.is_not(None), User.moodle_refresh_at <= now,
        ).order_by(User.moodle_refresh_at).limit(200)))

    def refresh(user_id: int) -> None:
        if stop is None or not stop.is_set():
            _refresh_one(user_id, now if stop is None else datetime.now(timezone.utc))

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="moodle-refresh") as pool:
        list(pool.map(refresh, due))


def start_worker() -> tuple[Event, Thread]:
    stop = Event()

    def run() -> None:
        while not stop.is_set():
            try:
                maintain_sessions(stop=stop)
            except Exception:
                # Параметры SQL в исключении могут содержать секреты.
                logger.error("Не удалось выполнить обслуживание Moodle-сессий")
            stop.wait(POLL_SECONDS)

    thread = Thread(target=run, name="moodle-sessions", daemon=True)
    thread.start()
    return stop, thread
