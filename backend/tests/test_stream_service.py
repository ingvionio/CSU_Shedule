"""Проверка сборки потока независимо от HTTP и пакета multipart."""

from datetime import date

import pytest

from app.models import Group, Lesson, Room
from app.schemas.admin import OverrideIn
from app.schemas.schedule import GroupOut, LessonOut
from app.services import overrides, schedule, stream_schedule
from app.services.groups import level_of
from tests.stream_data import stream_factory  # noqa: F401

TODAY = date(2026, 11, 16)


def build(db, ids=(1, 2), week=12):
    return stream_schedule.build_stream_schedule(
        db, stream_schedule.load_groups(db, list(ids)), schedule.active_semester(db), week, TODAY,
    )[1]


def items(days):
    return [item for day in days for item in day["lessons"]]


def change(db, ids=(1, 2), **fields):
    data = OverrideIn(group_ids=list(ids), date=TODAY, **fields)
    return overrides.create_overrides(db, schedule.active_semester(db), data, "admin", TODAY)


@pytest.mark.parametrize("direction,expected", [
    ("МПрИ", "master"), ("МИТ", "master"), ("МПИ", "master"), ("МБИ", "master"),
    ("ПрИ", "bachelor"), (None, "bachelor"), ("Неизвестное", "bachelor"),
])
def test_level_and_group_schema(direction, expected):
    assert level_of(direction) == expected
    group = Group(id=1, name="Тест", course=1, direction=direction)
    assert GroupOut.model_validate(group).model_dump()["level"] == expected


def test_intersection_primary_order_and_no_notes(stream_factory):
    with stream_factory() as db:
        days = build(db)
        assert len(days) == 6
        item, = items(days)
        assert item["id"] == "l-1" and item["note_key"] is None and item["stream_diff"] is None
        assert items(build(db, (2, 1)))[0]["id"] == "l-3"
        assert items(build(db, (1, 2, 5))) == []
        _, ordinary = schedule.build_week_schedule(db, db.get(Group, 1), schedule.active_semester(db), 12, TODAY)
        assert all(LessonOut.model_validate(item).stream_diff is None and item["note_key"]
                   for item in items(ordinary))


@pytest.mark.parametrize("ids", [(1,), (1, 1), (1, 3), (1, 4), ()])
def test_invalid_groups(stream_factory, ids):
    with stream_factory() as db:
        with pytest.raises(stream_schedule.StreamScheduleError):
            stream_schedule.load_groups(db, list(ids))


def test_room_teacher_type_and_time_differences(stream_factory):
    with stream_factory() as db:
        db.get(Lesson, 3).room = Room(name="326")
        db.commit()
        assert items(build(db))[0]["stream_diff"] == ["ИТ1-ПИб-11: ауд. 326"]
        change(db, (2,), kind="replace", source_lesson_id=3, start_time="18:00", end_time="19:30",
               subject="Другой предмет", lesson_type="practice", teacher="Другой преподаватель")
        details = " ".join(items(build(db))[0]["stream_diff"])
        for value in ("изменена", "18:00–19:30", "326", "Другой преподаватель", "Практика", "Другой предмет"):
            assert value in details


def test_stream_replacement_and_batch_revert(stream_factory):
    with stream_factory() as db:
        _, created = change(db, kind="replace", source_lesson_id=1, subject="Новый предмет",
                            start_time="18:00", end_time="19:30", room="326")
        item, = items(build(db))
        assert item["status"] == "changed" and item["subject"] == "Новый предмет"
        assert item["start_time"] == "18:00" and item["stream_diff"] is None
        assert item["id"] == "l-1" and item["change"]["override_id"] == created[0].id
        assert overrides.delete_override(db, item["change"]["override_id"], True) == 2
        assert items(build(db))[0]["status"] == "regular"


def test_single_group_cancellation(stream_factory):
    with stream_factory() as db:
        change(db, (2,), kind="cancel", source_lesson_id=3)
        item, = items(build(db))
        assert item["status"] == "regular" and item["stream_diff"] == ["ИТ1-ПИб-11: отменена"]
        reverse, = items(build(db, (2, 1)))
        assert reverse["status"] == "cancelled" and reverse["stream_diff"] == ["ИТ1-ПрИб-11: без изменений"]


def test_added_batch_identity(stream_factory):
    with stream_factory() as db:
        _, added = change(db, kind="add", subject="Дополнительная", slot=3, lesson_type="lecture")
        for group in (1, 2):
            change(db, (group,), kind="add", subject="Раздельная", slot=4, lesson_type="lecture")
        common = items(build(db))
        assert [item["subject"] for item in common] == ["Общая пара", "Дополнительная"]
        assert common[1]["id"] == f"o-{added[0].id}" and common[1]["stream_diff"] is None


@pytest.mark.parametrize("target,week", [(date(2026, 11, 18), 12), (date(2026, 11, 23), 13)])
def test_moved_in_uses_original_subject_across_weeks(stream_factory, target, week):
    with stream_factory() as db:
        _, moved = change(db, kind="move", source_lesson_id=1, target_date=target,
                          subject="Другой предмет", slot=3)
        original = items(build(db))[0]
        assert original["status"] == "moved_out" and original["stream_diff"] is None
        incoming, = [item for item in items(build(db, week=week)) if item["status"] == "moved_in"]
        assert incoming["id"] == f"o-{moved[0].id}" and incoming["stream_diff"] is None
        assert incoming["change"]["moved_from"]["date"] == TODAY.isoformat()


def test_single_move_and_different_destinations(stream_factory):
    with stream_factory() as db:
        change(db, (2,), kind="move", source_lesson_id=3, target_date=date(2026, 11, 18), slot=3)
        assert "перенесена, на 18.11.2026" in items(build(db))[0]["stream_diff"][0]
        change(db, (1,), kind="move", source_lesson_id=1, target_date=date(2026, 11, 19), slot=4)
        common = items(build(db))
        assert len(common) == 2
        assert all(item["stream_diff"] for item in common)
        assert "18.11.2026" in common[1]["stream_diff"][0]
