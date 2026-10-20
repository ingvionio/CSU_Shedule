"""Сквозные тесты: реальный Excel -> база -> API.

Проверяется контракт из 03-schedule-json.md.
"""

import pytest


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_список_групп(client):
    groups = client.get("/api/v1/groups").json()

    assert len(groups) == 15
    assert {group["course"] for group in groups} == {1, 2, 3, 4}
    # Имена сохранены как в файле.
    names = {group["name"] for group in groups}
    assert "ИТ1-ПрИб-11" in names
    assert "ПИ 201" in names


def test_сетка_звонков(client):
    slots = client.get("/api/v1/time-slots").json()

    assert len(slots) == 8
    assert slots[0] == {"number": 1, "start_time": "08:00", "end_time": "09:30"}
    assert slots[3] == {"number": 4, "start_time": "13:15", "end_time": "14:45"}


def test_текущая_неделя(client):
    week = client.get("/api/v1/weeks/current").json()

    assert 1 <= week["number"] <= 18
    assert week["parity"] in {"odd", "even"}
    assert week["semester"]["total_weeks"] == 18


def test_структура_ответа_недели(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ПИ 201']}/schedule", params={"week": 7}).json()

    assert data["group"] == {"id": group_ids["ПИ 201"], "name": "ПИ 201", "course": 2}
    assert data["week"] == {
        "number": 7,
        "parity": "odd",
        "start_date": "2026-10-12",
        "end_date": "2026-10-18",
        "is_current": data["week"]["is_current"],
        "prev": 6,
        "next": 8,
    }
    # Дни пн-сб приходят всегда, включая дни без пар.
    assert [day["weekday"] for day in data["days"]] == [1, 2, 3, 4, 5, 6]
    assert data["generated_at"]


def test_поля_пары(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ПИ 201']}/schedule", params={"week": 7}).json()
    lesson = data["days"][0]["lessons"][0]

    assert lesson["id"].startswith("l-")
    assert lesson["start_time"] == "08:00"
    assert lesson["end_time"] == "09:30"
    assert lesson["slot"] == 1
    assert lesson["type"]["code"] == "lecture"
    assert lesson["type"]["name"] == "Лекция"
    assert lesson["status"] == "regular"
    assert lesson["change"] is None


def test_пары_дня_отсортированы_по_времени(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ИТ1-ПрИб-11']}/schedule", params={"week": 7}).json()

    for day in data["days"]:
        times = [lesson["start_time"] for lesson in day["lessons"]]
        assert times == sorted(times)


def test_мигалка_разные_пары_на_чётной_и_нечётной(client, group_ids):
    group_id = group_ids["ПИ 201"]
    odd = client.get(f"/api/v1/groups/{group_id}/schedule", params={"week": 7}).json()
    even = client.get(f"/api/v1/groups/{group_id}/schedule", params={"week": 8}).json()

    assert odd["week"]["parity"] == "odd"
    assert even["week"]["parity"] == "even"

    # Пятница и суббота у ПИ 201 стоят только по чётным неделям.
    assert odd["days"][4]["lessons"] == []
    assert odd["days"][5]["lessons"] == []
    assert len(even["days"][4]["lessons"]) == 3
    assert len(even["days"][5]["lessons"]) == 4


def test_пара_вне_сетки_звонков(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ПИ 301']}/schedule", params={"week": 7}).json()
    off_grid = [lesson for day in data["days"] for lesson in day["lessons"] if lesson["slot"] is None]

    assert off_grid, "ожидалась пара с временем из ячейки (с 19:00)"
    assert off_grid[0]["start_time"] == "19:00"
    assert off_grid[0]["end_time"] == "20:30"


def test_ограничение_по_неделям_соблюдается(client, group_ids):
    """«СОВР.ТЕХНОЛОГИИ ... (1-7 НЕД.)» не должна попадать в 9-ю неделю."""
    group_id = group_ids["ИТ1-БИб-11"]

    def subjects(week: int) -> set[str]:
        data = client.get(f"/api/v1/groups/{group_id}/schedule", params={"week": week}).json()
        return {lesson["subject"] for day in data["days"] for lesson in day["lessons"]}

    assert any("СОВР.ТЕХНОЛОГИИ" in subject for subject in subjects(1))
    assert not any("СОВР.ТЕХНОЛОГИИ" in subject for subject in subjects(9))


def test_без_номера_недели_отдаётся_текущая(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ПИ 201']}/schedule").json()

    assert data["week"]["is_current"] is True


@pytest.mark.parametrize(("week", "status"), [(0, 422), (19, 404), (99, 404)])
def test_неделя_вне_семестра(client, group_ids, week, status):
    response = client.get(f"/api/v1/groups/{group_ids['ПИ 201']}/schedule", params={"week": week})

    assert response.status_code == status


def test_неизвестная_группа(client):
    assert client.get("/api/v1/groups/9999/schedule").status_code == 404


def test_даты_дней_совпадают_с_неделей(client, group_ids):
    data = client.get(f"/api/v1/groups/{group_ids['ПИ 201']}/schedule", params={"week": 8}).json()

    assert data["days"][0]["date"] == data["week"]["start_date"]
    assert data["days"][5]["date"] == "2026-10-24"  # суббота
