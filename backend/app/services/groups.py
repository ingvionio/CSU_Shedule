"""Направления подготовки (поток) по названию группы."""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group

# Магистерские коды раньше бакалаврских, чтобы потоки не смешивались.
MASTER_DIRECTIONS = ("МПрИ", "МИТ", "МПИ", "МБИ")
DIRECTION_PATTERN = re.compile("(" + "|".join((*MASTER_DIRECTIONS, "ПрИ", "ПИ", "БИ")) + ")")


def level_of(direction: str | None) -> Literal["bachelor", "master"]:
    return "master" if direction in MASTER_DIRECTIONS else "bachelor"


def group_key(name: str) -> str:
    """Ключ сравнения названий: без пробелов, дефисов и регистра («ПрИ-402» == «ПрИ 402»)."""
    return re.sub(r"[\s\-_—–]", "", name).lower()


async def find_group(session: AsyncSession, name: str) -> Group | None:
    """Группа с этим названием, в том числе записанным иначе.

    Вход через Moodle может создать группу раньше загрузки расписания и под
    другим написанием («ПрИ-402» вместо «ПрИ 402»). Такую группу не дублируем,
    а переименовываем так, как в файле: студенты и их данные остаются при ней.
    """
    group = await session.scalar(select(Group).where(Group.name == name))
    if group is not None:
        return group
    key = group_key(name)
    group = next((item for item in await session.scalars(select(Group).order_by(Group.id)) if group_key(item.name) == key), None)
    if group is not None:
        group.name = name
    return group


async def existing_group_ids(session: AsyncSession, names: list[str]) -> dict[str, int]:
    """Название из файла → id уже существующей группы (по тем же правилам, что `find_group`), без изменений в БД."""
    by_key = {group_key(group.name): group.id for group in await session.scalars(select(Group).order_by(Group.id.desc()))}
    exact = dict((await session.execute(select(Group.name, Group.id).where(Group.name.in_(names)))).all())
    return {name: exact.get(name, by_key.get(group_key(name))) for name in names
            if name in exact or group_key(name) in by_key}


def direction_of(name: str) -> str | None:
    """«ИТ1-ПрИб-11» -> «ПрИ», «ПИ 201» -> «ПИ». Неизвестное направление — None."""
    match = DIRECTION_PATTERN.search(name)
    return match.group(1) if match else None
