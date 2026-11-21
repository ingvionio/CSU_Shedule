import pytest
from sqlalchemy import select

from app.core.db import get_db
from app.core.security import issue_token
from app.main import app
from app.models import Lesson, LessonOverride, Room
from tests.stream_data import stream_factory  # noqa: F401
from tests import asgi_client


@pytest.fixture
def stream_db(stream_factory):
    async def dependency():
        async with stream_factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        yield stream_factory
    finally:
        app.dependency_overrides.pop(get_db)


@pytest.fixture
async def stream_client(stream_db):
    async with asgi_client(app) as client:
        yield client


@pytest.fixture
def headers():
    token, _ = issue_token("admin", "admin", 1)
    return {"Authorization": f"Bearer {token}"}


async def stream(client, headers, ids=(1, 2), week=12):
    return await client.get("/api/v1/admin/stream-schedule", headers=headers,
                      params=[*(('group_ids', value) for value in ids), ("week", week)])


def lessons(data):
    return [lesson for day in data["days"] for lesson in day["lessons"]]


async def override(client, headers, ids=(1, 2), **fields):
    return await client.post("/api/v1/admin/overrides", headers=headers, json={
        "group_ids": list(ids), "date": "2026-11-16", "source_lesson_id": 1, **fields,
    })


async def test_group_levels(stream_client):
    groups = {item["name"]: item for item in (await stream_client.get("/api/v1/groups")).json()}
    assert groups["МИТ 101"]["level"] == "master"
    assert groups["ИТ1-ПрИб-11"]["level"] == "bachelor"


async def test_default_week_and_unknown_group(stream_client, headers):
    response = await stream_client.get("/api/v1/admin/stream-schedule?group_ids=1&group_ids=2", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["week"]["number"] == (await stream_client.get("/api/v1/weeks/current")).json()["number"]
    assert (await stream(stream_client, headers, ids=(1, 999))).status_code == 404


@pytest.mark.parametrize("direction,expected", [
    ("МПрИ", "master"), ("МИТ", "master"), ("МПИ", "master"), ("МБИ", "master"),
    ("ПрИ", "bachelor"), (None, "bachelor"), ("Неизвестное", "bachelor"),
])
def test_level_of(direction, expected):
    from app.services.groups import level_of

    assert level_of(direction) == expected


async def test_only_common_lessons_and_primary_identity(stream_client, headers):
    response = await stream(stream_client, headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["days"]) == 6 and data["week"]["number"] == 12
    common, = lessons(data)
    assert common["id"] == "l-1" and common["subject"] == "Общая пара"
    assert common["stream_diff"] is None and common["note_key"] is None
    reverse = (await stream(stream_client, headers, ids=(2, 1))).json()
    assert reverse["group"]["id"] == 2 and lessons(reverse)[0]["id"] == "l-3"
    ordinary = (await stream_client.get("/api/v1/groups/1/schedule?week=12")).json()
    assert all(item["stream_diff"] is None and item["note_key"] for item in lessons(ordinary))


async def test_different_room(stream_client, stream_db, headers):
    async with stream_db() as db:
        lesson = await db.get(Lesson, 3)
        lesson.room = Room(name="326")
        await db.commit()
    item, = lessons((await stream(stream_client, headers)).json())
    assert item["stream_diff"] == ["ИТ1-ПИб-11: ауд. 326"]


async def test_stream_replacement_matches_original_subject_and_time(stream_client, headers):
    response = await override(stream_client, headers, kind="replace", subject="Новый предмет",
                        start_time="18:00", end_time="19:30", room="326")
    assert response.status_code == 201, response.text
    item, = lessons((await stream(stream_client, headers)).json())
    assert item["id"] == "l-1" and item["status"] == "changed"
    assert item["subject"] == "Новый предмет" and item["start_time"] == "18:00"
    assert item["stream_diff"] is None
    assert item["change"]["override_id"] == response.json()["override_ids"][0]


async def test_cancel_only_one_group(stream_client, headers):
    assert (await override(stream_client, headers, ids=(2,), source_lesson_id=3, kind="cancel")).status_code == 201
    item, = lessons((await stream(stream_client, headers)).json())
    assert item["status"] == "regular"
    assert item["stream_diff"] == ["ИТ1-ПИб-11: отменена"]


async def test_added_lessons_match_only_shared_batch(stream_client, headers):
    response = await override(stream_client, headers, kind="add", source_lesson_id=None,
                        subject="Общая дополнительная", slot=3, lesson_type="practice")
    assert response.status_code == 201, response.text
    # Одинаковые доп. пары, созданные разными действиями, общими не считаются.
    for ids in ((1,), (2,)):
        assert (await override(stream_client, headers, ids=ids, kind="add", source_lesson_id=None,
                        subject="Отдельная дополнительная", slot=4, lesson_type="lecture")).status_code == 201
    items = lessons((await stream(stream_client, headers)).json())
    assert [item["subject"] for item in items] == ["Общая пара", "Общая дополнительная"]
    assert items[1]["id"] == f"o-{response.json()['override_ids'][0]}"
    assert items[1]["stream_diff"] is None and items[1]["note_key"] is None


@pytest.mark.parametrize("target,week", [("2026-11-18", 12), ("2026-11-23", 13)])
async def test_stream_move_keeps_both_occurrences(stream_client, headers, target, week):
    response = await override(stream_client, headers, kind="move", target_date=target,
                        subject="Перенесённый предмет", slot=3)
    assert response.status_code == 201, response.text
    original = lessons((await stream(stream_client, headers)).json())
    assert original[0]["status"] == "moved_out" and original[0]["id"] == "l-1"
    incoming = [item for item in lessons((await stream(stream_client, headers, week=week)).json())
                if item["status"] == "moved_in"]
    assert len(incoming) == 1
    assert incoming[0]["id"] == f"o-{response.json()['override_ids'][0]}"
    assert incoming[0]["stream_diff"] is None
    assert incoming[0]["change"]["moved_from"]["date"] == "2026-11-16"


async def test_move_diff_uses_original_occurrence(stream_client, headers):
    response = await override(stream_client, headers, ids=(2,), source_lesson_id=3, kind="move",
                        target_date="2026-11-18", slot=3)
    assert response.status_code == 201, response.text
    item, = lessons((await stream(stream_client, headers)).json())
    assert "перенесена" in " ".join(item["stream_diff"])
    assert "18.11.2026" in " ".join(item["stream_diff"])


@pytest.mark.parametrize("ids", [(1,), (1, 1), (1, 3), (1, 4), ()])
async def test_invalid_stream(stream_client, headers, ids):
    response = await stream(stream_client, headers, ids=ids)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert any("а" <= char <= "я" for char in response.json()["detail"])


async def test_stream_requires_admin(stream_client):
    assert (await stream(stream_client, {})).status_code == 401
    token, _ = issue_token("1", "student", 1)
    assert (await stream(stream_client, {"Authorization": f"Bearer {token}"})).status_code == 403


async def test_no_common_lessons_preserves_days(stream_client, headers):
    data = (await stream(stream_client, headers, ids=(1, 2, 5))).json()
    assert len(data["days"]) == 6 and all(day["lessons"] == [] for day in data["days"])


async def test_stream_batch_revert(stream_client, headers, stream_db):
    response = await override(stream_client, headers, kind="replace", teacher="Другой преподаватель")
    item, = lessons((await stream(stream_client, headers)).json())
    result = await stream_client.delete(f"/api/v1/admin/overrides/{item['change']['override_id']}?batch=true",
                                  headers=headers)
    assert result.json() == {"deleted": 2}
    assert response.status_code == 201
    assert lessons((await stream(stream_client, headers)).json())[0]["status"] == "regular"
    async with stream_db() as db:
        assert await db.scalar(select(LessonOverride)) is None
