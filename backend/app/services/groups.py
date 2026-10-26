"""Направления подготовки (поток) по названию группы."""

from __future__ import annotations

import re

# «ПрИ» раньше «ПИ»: иначе «ИТ1-ПрИб-11» не найдётся, а «ПИ» совпадёт внутри другого слова.
DIRECTION_PATTERN = re.compile(r"(ПрИ|ПИ|БИ)")


def direction_of(name: str) -> str | None:
    """«ИТ1-ПрИб-11» -> «ПрИ», «ПИ 201» -> «ПИ». Неизвестное направление — None."""
    match = DIRECTION_PATTERN.search(name)
    return match.group(1) if match else None
