"""События в расписании, границы недель и изоляция от разовых пар."""
from datetime import date, time

from sqlalchemy import select

from app.models import Group, Semester
from app.models.exam import ExamEvent
from app.services import schedule
from tests.test_stream_schedule import (headers, lessons, override, stream, stream_client, stream_db)  # noqa: F401
from tests.stream_data import stream_factory  # noqa: F401


async def add_event(db, **fields):
    event = ExamEvent(**{"semester_id": 1, "kind": "session", "date": date(2026, 11, 16),
                         "subject": "Экзамен", "source": "manual", **fields})
    db.add(event)
    await db.commit()
    return event


async def test_mixed_day_order_and_event_contract(stream_client, stream_db):
    async with stream_db() as db:
        groups = list(await db.scalars(select(Group).where(Group.id.in_([1, 2]))))
        timed = await add_event(db, groups=groups, start_time=time(9, 40), event_type="exam",
                          teacher="Иванов", room="132", note="Взять зачётку")
        no_time = await add_event(db, groups=groups, event_type="consultation")
        off_grid = await add_event(db, groups=groups, start_time=time(15, 15))
        ids = [f"e-{no_time.id}", "l-1", f"e-{timed.id}", f"e-{off_grid.id}"]
    data = (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=12")).json()
    items = data["days"][0]["lessons"]
    assert [item["id"] for item in items] == ids
    assert items[0]["start_time"] is None and items[0]["slot"] is None
    assert items[1]["event"] is None and items[1]["note_key"]
    assert items[2] == {
        "id": ids[2], "note_key": None, "stream_diff": None,
        "start_time": "09:40", "end_time": None, "slot": 2,
        "subject": "Экзамен", "type": {"code": "exam", "name": "Экзамен"},
        "room": "132", "teacher": "Иванов", "online_url": None, "subgroup": None,
        "status": "regular", "change": None,
        "event": {"kind": "session", "note": "Взять зачётку", "groups": ["ИТ1-ПИб-11", "ИТ1-ПрИб-11"]},
    }
    assert items[3]["slot"] is None and items[3]["end_time"] is None
    assert len(data["days"]) == 6


async def test_extended_range_and_default_week(stream_client, stream_db, monkeypatch):
    async with stream_db() as db:
        semester = await db.get(Semester, 1)
        group = await db.get(Group, 1)
        # Событие другой группы тоже расширяет единый диапазон семестра.
        await add_event(db, groups=[await db.get(Group, 2)], date=date(2027, 1, 24), start_time=time(15))
        old = Semester(title="Старый", start_date=date(2025, 9, 1), end_date=date(2026, 1, 1),
                       total_weeks=18, is_active=False)
        db.add(old)
        await db.flush()
        db.add(ExamEvent(semester_id=old.id, kind="session", date=date(2028, 1, 1),
                         subject="Старый", source="manual", groups=[group]))
        await db.commit()
        week, _ = await schedule.build_week_schedule(db, group, semester, 18, date(2027, 1, 19))
        assert week.next == 19
    from app.api.v1 import public
    monkeypatch.setattr(public, "_today", lambda: date(2027, 1, 19))
    response = await stream_client.get("/api/v1/groups/1/schedule?events=1&week=21")
    assert response.status_code == 200, response.text
    assert lessons(response.json()) == []
    week = response.json()["week"]
    assert week["next"] is None and week["prev"] == 20 and week["parity"] == "odd"
    assert (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=22")).status_code == 404
    default = (await stream_client.get("/api/v1/groups/1/schedule?events=1")).json()["week"]
    assert default["number"] == 21 and default["is_current"]
    assert (await stream_client.get("/api/v1/weeks/current")).json()["number"] == 21
    sunday = (await stream_client.get("/api/v1/groups/2/schedule?events=1&week=21")).json()["days"][-1]
    assert sunday["date"] == "2027-01-24" and sunday["weekday"] == 7
    assert sunday["lessons"][0]["start_time"] == "15:00"


async def test_original_range_without_events(stream_client):
    data = (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=18")).json()
    assert data["week"]["next"] is None and len(data["days"]) == 6
    assert (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=19")).status_code == 404


async def test_events_do_not_conflict_or_enter_stream_and_notes(stream_client, stream_db, headers):
    async with stream_db() as db:
        await add_event(db, groups=[await db.get(Group, 1), await db.get(Group, 2)], start_time=time(11, 20))
        day = await schedule.build_day(db, await db.get(Group, 1), await db.get(Semester, 1),
                                 date(2026, 11, 16), date(2026, 11, 16))
        assert all(not item["id"].startswith("e-") for item in day["lessons"])
    response = await override(stream_client, headers, kind="add", source_lesson_id=None,
                        subject="Дополнительная", slot=3, lesson_type="practice")
    assert response.status_code == 201, response.text
    assert not any(item["id"].startswith("e-") for item in lessons((await stream(stream_client, headers)).json()))
    assert any(item["id"].startswith("e-") for item in lessons(
        (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=12")).json()))


async def test_master_exam_only_is_not_pending(stream_client, stream_db, monkeypatch):
    from app.api.v1 import public
    monkeypatch.setattr(public, "_today", lambda: date(2026, 11, 16))
    async with stream_db() as db:
        await add_event(db, groups=[await db.get(Group, 3)])
    data = (await stream_client.get("/api/v1/groups/3/schedule?events=1&week=12")).json()
    assert data["week"]["schedule_pending"] is False
    assert len(lessons(data)) == 1


async def test_filled_empty_field_is_not_a_change(stream_client, stream_db):
    async with stream_db() as db:
        groups = list(await db.scalars(select(Group).where(Group.id == 1)))
        # аудитории и времени не было — их проставили: не «изменено»
        filled = await add_event(db, groups=groups, start_time=time(9, 40), room="132а",
                           original={"start_time": None, "room": None})
        # аудитория была и поменялась — «изменено», прежнее значение в change
        moved = await add_event(db, groups=groups, start_time=time(11, 20), room="132а",
                          original={"start_time": None, "room": "132"})
        ids = {f"e-{filled.id}": "filled", f"e-{moved.id}": "moved"}
    items = {ids[item["id"]]: item for item in
             (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=12")).json()["days"][0]["lessons"] if item["id"] in ids}
    assert items["filled"]["status"] == "regular" and items["filled"]["change"] is None
    assert items["moved"]["status"] == "changed"
    assert items["moved"]["change"] == {"original": {"room": "132"}}


async def test_old_clients_get_schedule_without_events(stream_client, stream_db):
    # APK 1.1.1 не просит события: неделя как раньше — без экзаменов и без воскресенья
    async with stream_db() as db:
        groups = list(await db.scalars(select(Group).where(Group.id == 1)))
        await add_event(db, groups=groups, event_type="exam")  # без времени — старый клиент на таком падал
        await add_event(db, groups=groups, date=date(2026, 11, 22), start_time=time(10, 0))  # воскресенье
    old = (await stream_client.get("/api/v1/groups/1/schedule?week=12")).json()
    assert all(not item["id"].startswith("e-") for day in old["days"] for item in day["lessons"])
    assert all(item["start_time"] and item["end_time"] for day in old["days"] for item in day["lessons"])
    assert len(old["days"]) == 6
    new = (await stream_client.get("/api/v1/groups/1/schedule?events=1&week=12")).json()
    assert sum(item["id"].startswith("e-") for day in new["days"] for item in day["lessons"]) == 2
    assert len(new["days"]) == 7
