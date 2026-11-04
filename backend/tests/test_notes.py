from datetime import date, time

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import Lesson, LessonOverride, PersonalNote, Semester, Subject
from app.services.importer import ensure_reference_data

API = "/api/v1"


@pytest.fixture
def notes_demo(bare_client, test_groups):
    group = test_groups["ТЕСТ ПИ 991"]
    with SessionLocal() as db:
        active = list(db.scalars(select(Semester).where(Semester.is_active.is_(True))))
        for semester in active:
            semester.is_active = False
        semester = Semester(title="Notes test", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3),
                            total_weeks=18, first_week_parity="odd", is_active=True)
        subject = Subject(name="Notes subject")
        db.add_all([semester, subject])
        ensure_reference_data(db)
        db.flush()
        lesson = Lesson(semester_id=semester.id, group_id=group, subject_id=subject.id,
                        weekday=1, start_time=time(8), end_time=time(9, 30), slot=1,
                        lesson_type="practice", week_parity="both", valid_from=date(2026, 9, 1), status="published")
        db.add(lesson)
        db.commit()
        ids = semester.id, subject.id, lesson.id
    def register(key):
        result = bare_client.post(f"{API}/auth/student/register", json={
            "full_name": "Notes Student", "group_id": group, "device_key": key,
        })
        assert result.status_code == 200
        return {"Authorization": f"Bearer {result.json()['access_token']}"}
    first = register("notes-owner-device-0001")
    second = register("notes-other-device-0001")
    yield group, ids[2], first, second
    with SessionLocal() as db:
        db.execute(delete(PersonalNote))
        db.execute(delete(LessonOverride).where(LessonOverride.semester_id == ids[0]))
        db.execute(delete(Lesson).where(Lesson.semester_id == ids[0]))
        db.execute(delete(Semester).where(Semester.id == ids[0]))
        db.execute(delete(Subject).where(Subject.id == ids[1]))
        for semester in active:
            db.get(Semester, semester.id).is_active = True
        db.commit()


def save(client, headers, group, lesson, **fields):
    return client.post(f"{API}/me/notes", headers=headers, json={
        "group_id": group, "lesson_date": "2026-11-02", "lesson_ref": f"l-{lesson}",
        "body": "Private text", "version": 0, **fields,
    })


def test_private_crud_and_roles(bare_client, bare_admin_headers, notes_demo):
    group, lesson, owner, other = notes_demo
    result = save(bare_client, owner, group, lesson)
    assert result.status_code == 200, result.text
    note = result.json()
    assert bare_client.get(f"{API}/me/notes", headers=owner).json()[0]["body"] == "Private text"
    assert bare_client.get(f"{API}/me/notes", headers=other).json() == []
    assert bare_client.get(f"{API}/me/notes", headers=bare_admin_headers).status_code == 403
    assert bare_client.get(f"{API}/me/notes").status_code == 401
    assert bare_client.delete(f"{API}/me/notes/{note['id']}?version=1", headers=other).status_code == 404
    own_other = save(bare_client, other, group, lesson, body="Other student's note")
    assert own_other.status_code == 200
    assert own_other.json()["id"] != note["id"]
    updated = save(bare_client, owner, group, lesson, body="Updated", version=1)
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert save(bare_client, owner, group, lesson, body="Stale", version=1).status_code == 409
    assert bare_client.delete(f"{API}/me/notes/{note['id']}?version=1", headers=owner).status_code == 409
    assert bare_client.delete(f"{API}/me/notes/{note['id']}?version=2", headers=owner).status_code == 204
    assert bare_client.get(f"{API}/me/notes", headers=owner).json() == []


def test_note_follows_move_and_is_specific_to_week(bare_client, bare_admin_headers, notes_demo):
    group, lesson, owner, _ = notes_demo
    note = save(bare_client, owner, group, lesson).json()
    other_week = save(bare_client, owner, group, lesson, lesson_date="2026-11-09", body="Next week").json()
    assert other_week["occurrence_key"] != note["occurrence_key"]
    moved = bare_client.post(f"{API}/admin/overrides", headers=bare_admin_headers, json={
        "group_ids": [group], "kind": "move", "date": "2026-11-02", "source_lesson_id": lesson,
        "target_date": "2026-11-10", "slot": 2,
    })
    assert moved.status_code == 201, moved.text
    week = bare_client.get(f"{API}/groups/{group}/schedule?week=11").json()
    incoming = next(item for day in week["days"] for item in day["lessons"] if item["status"] == "moved_in")
    assert incoming["note_key"] == note["occurrence_key"]
    update = save(bare_client, owner, group, lesson, lesson_date="2026-11-10",
                  lesson_ref=incoming["id"], version=1, body="After move")
    assert update.status_code == 200, update.text
    assert update.json()["id"] == note["id"]


def test_invalid_and_blank_notes(bare_client, notes_demo):
    group, lesson, owner, _ = notes_demo
    assert save(bare_client, owner, group, lesson, body="  ").status_code == 422
    assert save(bare_client, owner, group, lesson, lesson_date="2026-11-03").status_code == 409
    assert save(bare_client, owner, group, lesson, lesson_date="2026-11-08").status_code == 422


def test_identity_survives_lesson_recreation(bare_client, notes_demo):
    group, lesson_id, owner, _ = notes_demo
    note = save(bare_client, owner, group, lesson_id).json()
    with SessionLocal() as db:
        old = db.get(Lesson, lesson_id)
        replacement = Lesson(semester_id=old.semester_id, group_id=old.group_id, subject_id=old.subject_id,
            weekday=old.weekday, start_time=old.start_time, end_time=old.end_time, slot=old.slot,
            lesson_type=old.lesson_type, week_parity=old.week_parity, valid_from=old.valid_from, status=old.status)
        db.add(replacement)
        db.flush()
        new_id = replacement.id
        db.delete(old)
        db.commit()
    response = save(bare_client, owner, group, new_id, version=1, body="Still my note")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == note["id"]
