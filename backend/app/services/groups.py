"""Направления подготовки (поток) по названию группы."""

from __future__ import annotations

import re
from typing import Literal

# Магистерские коды раньше бакалаврских, чтобы потоки не смешивались.
MASTER_DIRECTIONS = ("МПрИ", "МИТ", "МПИ", "МБИ")
DIRECTION_PATTERN = re.compile("(" + "|".join((*MASTER_DIRECTIONS, "ПрИ", "ПИ", "БИ")) + ")")


def level_of(direction: str | None) -> Literal["bachelor", "master"]:
    return "master" if direction in MASTER_DIRECTIONS else "bachelor"


def direction_of(name: str) -> str | None:
    """«ИТ1-ПрИб-11» -> «ПрИ», «ПИ 201» -> «ПИ». Неизвестное направление — None."""
    match = DIRECTION_PATTERN.search(name)
    return match.group(1) if match else None
