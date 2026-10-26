"""Профиль студента: регистрация по ФИО и группе с привязкой к устройству."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Group, User
from app.services.feedback import secret_hash


class StudentError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_name(value: str) -> str:
    """Лишние пробелы не должны превращать одного студента в двух."""
    return " ".join(value.split())


def register(
    db: Session,
    full_name: str,
    group_id: int,
    device_key: str,
    ip: str | None,
    now: datetime | None = None,
) -> tuple[User, bool]:
    """Находит студента по ключу устройства или заводит нового.

    Возвращает пользователя и признак «группа назначена заново» (новый
    профиль или смена группы) — тогда ему досылаются недавние сообщения.
    """
    now = now or datetime.now(timezone.utc)
    name = normalize_name(full_name)
    if len(name) < 3:
        raise StudentError("укажите фамилию и имя", 422)
    if db.get(Group, group_id) is None:
        raise StudentError("группа не найдена", 404)

    device_hash = secret_hash(device_key)
    user = db.scalar(select(User).where(User.device_key_hash == device_hash))
    if user is None:
        ip_hash = secret_hash(ip) if ip else None
        if ip_hash:
            recent = db.scalar(
                select(func.count(User.id)).where(User.ip_hash == ip_hash, User.created_at >= now - timedelta(hours=1))
            )
            if recent >= get_settings().student_register_ip_limit_per_hour:
                raise StudentError("слишком много регистраций, попробуйте через час", 429)
        user = User(full_name=name, group_id=group_id, device_key_hash=device_hash, ip_hash=ip_hash, created_at=now)
        db.add(user)
        group_changed = True
    else:
        group_changed = user.group_id != group_id
        user.full_name = name
        user.group_id = group_id

    user.last_seen_at = now
    db.flush()
    db.refresh(user, ["group"])
    db.commit()
    return user, group_changed


def get_student(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise StudentError("профиль не найден, зарегистрируйтесь заново", 401)
    return user
