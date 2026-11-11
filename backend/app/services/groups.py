"""Направления подготовки (поток) по названию группы."""

from __future__ import annotations

import re

# Магистерские коды раньше бакалаврских, чтобы потоки не смешивались.
DIRECTION_PATTERN = re.compile(r"(МПрИ|МИТ|МПИ|МБИ|ПрИ|ПИ|БИ)")


def direction_of(name: str) -> str | None:
    """«ИТ1-ПрИб-11» -> «ПрИ», «ПИ 201» -> «ПИ». Неизвестное направление — None."""
    match = DIRECTION_PATTERN.search(name)
    return match.group(1) if match else None
