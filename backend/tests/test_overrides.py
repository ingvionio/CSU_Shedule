"""Временные изменения: вход админа, отмена, перенос, замена, доп. пара, поток.

Тесты меняют общую базу, поэтому работают с неделями 12-14 (другие тесты
их не смотрят) и после каждого теста удаляют все изменения.
"""

from collections import defaultdict

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.models import LessonOverride

WEEK = 12


@pytest.fixture(autouse=True)
async def _clean_overrides(filled_db):
    yield
    async with SessionLocal() as session:
        await session.execute(delete(LessonOverride))
        await session.commit()


async def week(client, group_id, number=WEEK):
    response = await client.get(f"/api/v1/groups/{group_id}/schedule", params={"week": number})
    assert response.status_code == 200
    return response.json()


def first_lesson(data):
    """Первая пара недели: (день, пара)."""
    for day in data["days"]:
        if day["lessons"]:
            return day, day["lessons"][0]
    raise AssertionError("в неделе нет пар")


def find(data, lesson_id):
    for day in data["days"]:
        for lesson in day["lessons"]:
            if lesson["id"] == lesson_id:
                return day, lesson
    return None, None


async def free_slot(client, data):
    """Свободная клетка сетки в неделе: (дата, номер пары)."""
    slots = (await client.get("/api/v1/time-slots")).json()
    for day in data["days"]:
        for slot in slots:
            if all(
                not (slot["start_time"] < lesson["end_time"] and lesson["start_time"] < slot["end_time"])
                for lesson in day["lessons"]
            ):
                return day["date"], slot["number"]
    raise AssertionError("нет свободной клетки")


async def post(client, headers, **body):
    return await client.post("/api/v1/admin/overrides", json=body, headers=headers)


def source_id(lesson):
    return int(lesson["id"].removeprefix("l-"))


# --- вход ---


async def test_вход_с_неверным_паролем(client):
    response = await client.post("/api/v1/auth/admin/login", json={"login": "admin", "password": "wrong"})
    assert response.status_code == 401


async def test_админка_без_входа_закрыта(client):
    assert (await client.get("/api/v1/admin/catalog")).status_code == 401
    response = await client.post("/api/v1/admin/overrides", json={"group_ids": [1], "kind": "cancel", "date": "2026-11-16"})
    assert response.status_code == 401
    bad = {"Authorization": "Bearer nonsense"}
    assert (await client.get("/api/v1/admin/catalog", headers=bad)).status_code == 401


async def test_справочники(client, admin_headers):
    data = (await client.get("/api/v1/admin/catalog", headers=admin_headers)).json()
    assert data["subjects"] and data["teachers"] and data["rooms"]

    types = (await client.get("/api/v1/lesson-types")).json()
    assert {"code": "lecture", "name": "Лекция"} in types


# --- отмена ---


async def test_отмена_и_откат(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))

    response = await post(client, admin_headers, group_ids=[group_id], kind="cancel",
                    date=day["date"], source_lesson_id=source_id(lesson), comment="Конференция")
    assert response.status_code == 201
    override_id = response.json()["override_ids"][0]

    _, cancelled = find(await week(client, group_id), lesson["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["change"]["kind"] == "cancel"
    assert cancelled["change"]["comment"] == "Конференция"
    assert cancelled["change"]["override_id"] == override_id

    # Через две недели (та же чётность) пара на месте.
    _, same_lesson = find(await week(client, group_id, WEEK + 2), lesson["id"])
    assert same_lesson["status"] == "regular"

    deleted = await client.delete(f"/api/v1/admin/overrides/{override_id}", headers=admin_headers)
    assert deleted.json() == {"deleted": 1}
    _, restored = find(await week(client, group_id), lesson["id"])
    assert restored["status"] == "regular"
    assert restored["change"] is None


async def test_повторное_изменение_заменяет_прежнее(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))
    body = dict(group_ids=[group_id], date=day["date"], source_lesson_id=source_id(lesson))

    assert (await post(client, admin_headers, kind="cancel", **body)).status_code == 201
    assert (await post(client, admin_headers, kind="replace", room="999", **body)).status_code == 201

    _, item = find(await week(client, group_id), lesson["id"])
    assert item["status"] == "changed"


async def test_нельзя_изменить_пару_не_в_свой_день(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    data = await week(client, group_id)
    day, lesson = first_lesson(data)
    other_day = next(item["date"] for item in data["days"] if item["date"] != day["date"])

    response = await post(client, admin_headers, group_ids=[group_id], kind="cancel",
                    date=other_day, source_lesson_id=source_id(lesson))
    assert response.status_code == 422


@pytest.mark.parametrize("bad_date", ["2026-11-22", "2027-06-01"])  # воскресенье, вне семестра
async def test_дата_вне_учебных_дней(client, admin_headers, group_ids, bad_date):
    response = await post(client, admin_headers, group_ids=[group_ids["ПИ 201"]], kind="add",
                    date=bad_date, slot=1, subject="Тест", lesson_type="practice")
    assert response.status_code == 422


# --- замена ---


async def test_замена_аудитории(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))

    response = await post(client, admin_headers, group_ids=[group_id], kind="replace",
                    date=day["date"], source_lesson_id=source_id(lesson),
                    subject=lesson["subject"], room="Новая-1", teacher=lesson["teacher"])
    assert response.status_code == 201

    _, changed = find(await week(client, group_id), lesson["id"])
    assert changed["status"] == "changed"
    assert changed["room"] == "Новая-1"
    assert changed["subject"] == lesson["subject"]
    assert changed["change"]["original"] == {"room": lesson["room"]}


# --- перенос ---


async def test_перенос_на_другую_неделю_вне_сетки(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))
    target = (await week(client, group_id, WEEK + 1))["days"][5]["date"]  # суббота следующей недели

    response = await post(client, admin_headers, group_ids=[group_id], kind="move",
                    date=day["date"], source_lesson_id=source_id(lesson),
                    target_date=target, start_time="21:30", end_time="23:00")
    assert response.status_code == 201, response.text
    override_id = response.json()["override_ids"][0]

    _, moved_out = find(await week(client, group_id), lesson["id"])
    assert moved_out["status"] == "moved_out"
    assert moved_out["change"]["moved_to"] == {"date": target, "slot": None, "start_time": "21:30", "end_time": "23:00"}

    target_day, moved_in = find(await week(client, group_id, WEEK + 1), f"o-{override_id}")
    assert target_day["date"] == target
    assert moved_in["status"] == "moved_in"
    assert moved_in["subject"] == lesson["subject"]
    assert moved_in["slot"] is None
    assert moved_in["change"]["moved_from"]["date"] == day["date"]
    assert moved_in["change"]["moved_from"]["start_time"] == lesson["start_time"]


async def test_своё_время_по_звонку_получает_номер_пары(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    data = await week(client, group_id)
    day, lesson = first_lesson(data)
    free_date, slot_number = await free_slot(client, data)
    slot = (await client.get("/api/v1/time-slots")).json()[slot_number - 1]

    response = await post(client, admin_headers, group_ids=[group_id], kind="move",
                    date=day["date"], source_lesson_id=source_id(lesson), target_date=free_date,
                    start_time=slot["start_time"], end_time=slot["end_time"])
    assert response.status_code == 201, response.text

    _, moved_in = find(await week(client, group_id), f"o-{response.json()['override_ids'][0]}")
    assert moved_in["slot"] == slot_number


async def test_перенос_на_занятое_время_запрещён(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    data = await week(client, group_id)
    day = next(item for item in data["days"] if len(item["lessons"]) >= 2)
    first, second = day["lessons"][0], day["lessons"][1]

    response = await post(client, admin_headers, group_ids=[group_id], kind="move",
                    date=day["date"], source_lesson_id=source_id(first), target_date=day["date"],
                    start_time=second["start_time"], end_time=second["end_time"])
    assert response.status_code == 409
    assert second["subject"] in response.json()["detail"]

    # Ничего не сохранилось.
    _, untouched = find(await week(client, group_id), first["id"])
    assert untouched["status"] == "regular"


# --- доп. пара ---


async def test_доп_пара(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    free_date, slot_number = await free_slot(client, await week(client, group_id))

    response = await post(client, admin_headers, group_ids=[group_id], kind="add", date=free_date,
                    slot=slot_number, subject="Отработка", lesson_type="practice",
                    teacher="Новый Преподаватель", room="")
    assert response.status_code == 201
    override_id = response.json()["override_ids"][0]

    day, added = find(await week(client, group_id), f"o-{override_id}")
    assert day["date"] == free_date
    assert added["status"] == "added"
    assert added["slot"] == slot_number
    assert added["type"]["code"] == "practice"
    assert added["teacher"] == "Новый Преподаватель"
    assert added["room"] is None


async def test_доп_пара_поверх_существующей_запрещена(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))

    response = await post(client, admin_headers, group_ids=[group_id], kind="add", date=day["date"],
                    start_time=lesson["start_time"], end_time=lesson["end_time"],
                    subject="Отработка", lesson_type="practice")
    assert response.status_code == 409


async def test_доп_пара_на_место_отменённой(client, admin_headers, group_ids):
    group_id = group_ids["ПИ 201"]
    day, lesson = first_lesson(await week(client, group_id))
    assert (await post(client, admin_headers, group_ids=[group_id], kind="cancel",
                date=day["date"], source_lesson_id=source_id(lesson))).status_code == 201

    response = await post(client, admin_headers, group_ids=[group_id], kind="add", date=day["date"],
                    start_time=lesson["start_time"], end_time=lesson["end_time"],
                    subject="Отработка", lesson_type="practice")
    assert response.status_code == 201


async def test_доп_пара_без_дисциплины(client, admin_headers, group_ids):
    response = await post(client, admin_headers, group_ids=[group_ids["ПИ 201"]], kind="add",
                    date="2026-11-16", slot=8, lesson_type="practice")
    assert response.status_code == 422


# --- поток ---


async def shared_lesson(client):
    """Пара, которая в неделе стоит одновременно у нескольких групп одного курса."""
    groups = [group for group in (await client.get("/api/v1/groups")).json() if group["course"] == 2]
    seen = defaultdict(list)
    for group in groups:
        for day in (await week(client, group["id"]))["days"]:
            for lesson in day["lessons"]:
                seen[(day["date"], lesson["start_time"], lesson["subject"])].append((group["id"], lesson))
    for (date, _, _), items in seen.items():
        if len({group_id for group_id, _ in items}) >= 2:
            return date, items
    pytest.skip("нет общих пар потока на 2 курсе")


async def test_отмена_для_потока_и_откат_для_всех(client, admin_headers):
    date, items = await shared_lesson(client)
    stream = list(dict.fromkeys(group_id for group_id, _ in items))
    source = items[0][1]

    response = await post(client, admin_headers, group_ids=stream, kind="cancel",
                    date=date, source_lesson_id=source_id(source))
    assert response.status_code == 201, response.text
    assert set(response.json()["group_ids"]) == set(stream)

    for group_id, lesson in items:
        _, item = find(await week(client, group_id), lesson["id"])
        assert item["status"] == "cancelled"

    first_override = response.json()["override_ids"][0]
    deleted = await client.delete(f"/api/v1/admin/overrides/{first_override}", params={"batch": True}, headers=admin_headers)
    assert deleted.json()["deleted"] == len(response.json()["override_ids"])

    for group_id, lesson in items:
        _, item = find(await week(client, group_id), lesson["id"])
        assert item["status"] == "regular"


async def test_замена_для_потока_сохраняет_аудитории_групп(client, admin_headers):
    """Админ меняет преподавателя; аудитория каждой группы остаётся своей."""
    date, items = await shared_lesson(client)
    stream = list(dict.fromkeys(group_id for group_id, _ in items))
    source = items[0][1]

    response = await post(client, admin_headers, group_ids=stream, kind="replace", date=date,
                    source_lesson_id=source_id(source), subject=source["subject"],
                    teacher="Замена Преподавателя", room=source["room"] or "")
    assert response.status_code == 201, response.text

    for group_id, lesson in items:
        _, item = find(await week(client, group_id), lesson["id"])
        assert item["teacher"] == "Замена Преподавателя"
        assert item["room"] == lesson["room"]


async def test_поток_с_группой_без_такой_пары(client, admin_headers):
    date, items = await shared_lesson(client)
    stream = {group_id for group_id, _ in items}
    source = items[0][1]
    # Группа другого курса: у неё этой пары точно нет.
    stranger = next(group["id"] for group in (await client.get("/api/v1/groups")).json() if group["course"] == 4)

    response = await post(client, admin_headers, group_ids=[*stream, stranger], kind="cancel",
                    date=date, source_lesson_id=source_id(source))
    assert response.status_code == 422

    for group_id, lesson in items:
        _, item = find(await week(client, group_id), lesson["id"])
        assert item["status"] == "regular"
