"""Направление подготовки (поток) у групп."""

import pytest

from app.services.groups import direction_of


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ИТ1-ПрИб-11", "ПрИ"),
        ("ПИ 201", "ПИ"),
        ("ПрИ 203", "ПрИ"),
        ("БИ 301", "БИ"),
        ("МПрИ 101", "МПрИ"),
        ("МИТ 101", "МИТ"),
        ("МПИ 101", "МПИ"),
        ("МБИ 101", "МБИ"),
        ("Магистратура", None),
    ],
)
def test_направление_из_названия(name, expected):
    assert direction_of(name) == expected


def test_список_направлений(bare_client, test_groups):
    directions = {item["code"]: item["courses"] for item in bare_client.get("/api/v1/directions").json()}
    # С реальным Excel в базе есть и другие курсы — проверяем только тестовые группы.
    assert {1, 2} <= set(directions["ПИ"])
    assert 1 in directions["БИ"]


def test_группа_отдаёт_направление(bare_client, test_groups):
    names = {group["name"]: group["direction"] for group in bare_client.get("/api/v1/groups").json()}
    assert names["ТЕСТ БИ 991"] == "БИ"
