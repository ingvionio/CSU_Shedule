"""Направление подготовки (поток) у групп."""

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.models import Group
from app.services.groups import direction_of


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ИТ1-ПрИб-11", "ПрИ"),
        ("ПИ 201", "ПИ"),
        ("ПрИ 203", "ПрИ"),
        ("БИ 301", "БИ"),
        ("Магистратура", None),
    ],
)
def test_направление_из_названия(name, expected):
    assert direction_of(name) == expected


@pytest.fixture
def groups(db_schema):
    with SessionLocal() as session:
        session.add_all(
            [
                Group(name="ТЕСТ ПИ 991", course=1, direction="ПИ"),
                Group(name="ТЕСТ ПИ 992", course=2, direction="ПИ"),
                Group(name="ТЕСТ БИ 991", course=1, direction="БИ"),
            ]
        )
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(Group).where(Group.name.like("ТЕСТ %")))
        session.commit()


def test_список_направлений(bare_client, groups):
    directions = {item["code"]: item["courses"] for item in bare_client.get("/api/v1/directions").json()}
    assert directions["ПИ"] == [1, 2]
    assert directions["БИ"] == [1]


def test_группа_отдаёт_направление(bare_client, groups):
    names = {group["name"]: group["direction"] for group in bare_client.get("/api/v1/groups").json()}
    assert names["ТЕСТ БИ 991"] == "БИ"
