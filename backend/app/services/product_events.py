"""Запись событий для статистики ЛК продукта."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ProductEvent, User
from app.services.feedback import secret_hash

logger = logging.getLogger(__name__)

# События, которые присылает клиент. Остальные имена от клиента пропускаются молча:
# старые и новые сборки не должны ломаться о список.
LANDING_VIEW = "landing_view"
LOGIN_CLICK = "login_click"
LOGIN_SUBMIT = "login_submit"
APP_OPEN = "app_open"
APK_DOWNLOAD = "apk_download"
SCHEDULE_DAY_VIEW = "schedule_day_view"
SCHEDULE_WEEK_VIEW = "schedule_week_view"
MAP_OPEN = "map_open"
HELP_OPEN = "help_open"
PUSH_OPEN = "push_open"  # приложение открыто нажатием на уведомление
CLIENT_EVENTS = frozenset({
    LANDING_VIEW, LOGIN_CLICK, LOGIN_SUBMIT, APP_OPEN, APK_DOWNLOAD,
    SCHEDULE_DAY_VIEW, SCHEDULE_WEEK_VIEW, MAP_OPEN, HELP_OPEN, PUSH_OPEN,
})

# События, которые пишет только сервер — им можно доверять.
LOGIN_SUCCESS = "login_success"
LOGIN_FAILED_AUTH = "login_failed_auth"
LOGIN_FAILED_GROUP = "login_failed_group"
LOGIN_FAILED_OTHER = "login_failed_other"
MESSAGE_RECEIVED = "message_received"  # студент попал в получатели (при отправке или досылке)
MESSAGE_READ = "message_read"  # первое открытие
MESSAGE_ACK = "message_ack"  # «Ознакомлен»
PUSH_SENT = "push_sent"  # уведомление доставлено хотя бы на одно устройство
PUSH_SUBSCRIBED = "push_subscribed"
FEEDBACK_SENT = "feedback_sent"
NOTE_SAVED = "note_saved"
SERVER_EVENTS = frozenset({
    LOGIN_SUCCESS, LOGIN_FAILED_AUTH, LOGIN_FAILED_GROUP, LOGIN_FAILED_OTHER,
    MESSAGE_RECEIVED, MESSAGE_READ, MESSAGE_ACK, PUSH_SENT, PUSH_SUBSCRIBED, FEEDBACK_SENT, NOTE_SAVED,
})

PLATFORMS = frozenset({"web", "pwa", "apk"})
_VERSION = re.compile(r"^[0-9A-Za-z.+_-]{1,32}$")


def normalize_platform(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if value in PLATFORMS else None


def normalize_version(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _VERSION.match(value) else None


def device_hash(device_key: str | None) -> str | None:
    device_key = (device_key or "").strip()
    return secret_hash(device_key) if device_key else None


def _event(
    name: str,
    *,
    now: datetime,
    user_id: int | None,
    device: str | None,
    platform: str | None,
    app_version: str | None,
) -> ProductEvent:
    return ProductEvent(
        occurred_at=now,
        name=name,
        user_id=user_id,
        device_hash=device,
        platform=normalize_platform(platform),
        app_version=normalize_version(app_version),
    )


def add_event(
    db: Session,
    name: str,
    *,
    user_id: int | None,
    now: datetime | None = None,
    message_id: int | None = None,
) -> None:
    """Добавляет серверное событие в текущую транзакцию — коммитит вызывающий код."""
    event = _event(
        name, now=now or datetime.now(timezone.utc), user_id=user_id, device=None, platform=None, app_version=None
    )
    if message_id is not None:
        event.props = {"message_id": message_id}
    db.add(event)


def accept_client_events(
    db: Session,
    *,
    names: Iterable[str],
    device_key: str,
    user_id: int | None,
    platform: str | None,
    app_version: str | None,
    now: datetime | None = None,
) -> int:
    """Сохраняет разрешённые клиентские события. Возвращает, сколько принято."""
    now = now or datetime.now(timezone.utc)
    device = device_hash(device_key)
    accepted = [name for name in names if name in CLIENT_EVENTS]
    if not accepted or device is None:
        return 0
    # Токен пережил удалённого студента — пишем событие как анонимное, а не падаем на внешнем ключе.
    if user_id is not None and db.get(User, user_id) is None:
        user_id = None

    recent = db.scalar(
        select(func.count(ProductEvent.id)).where(
            ProductEvent.device_hash == device,
            ProductEvent.occurred_at >= now - timedelta(hours=1),
        )
    ) or 0
    room = max(get_settings().product_events_limit_per_hour - recent, 0)
    accepted = accepted[:room]
    db.add_all(
        _event(name, now=now, user_id=user_id, device=device, platform=platform, app_version=app_version)
        for name in accepted
    )
    db.commit()
    return len(accepted)


def record_server_event(
    db: Session,
    name: str,
    *,
    user_id: int | None,
    device_key: str | None = None,
    platform: str | None = None,
    app_version: str | None = None,
    now: datetime | None = None,
) -> None:
    """Пишет серверное событие отдельной транзакцией. Ошибка записи не мешает основному действию."""
    try:
        db.add(
            _event(
                name,
                now=now or datetime.now(timezone.utc),
                user_id=user_id,
                device=device_hash(device_key),
                platform=platform,
                app_version=app_version,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 — статистика не должна ломать вход
        db.rollback()
        logger.exception("Не удалось записать событие статистики %s", name)
