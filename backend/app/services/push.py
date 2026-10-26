"""Push-уведомления о сообщениях. Пока не подключены: инбокс работает и без них."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_message(message_id: int, user_ids: list[int], reminder: bool) -> None:
    """Фоновая задача после ответа API."""
    if user_ids:
        logger.info("Push не настроен: сообщение %s, получателей %s", message_id, len(user_ids))
