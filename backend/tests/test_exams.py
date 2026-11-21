"""Импорт, права и готовое расписание сессии."""
from datetime import date, time

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import issue_token
from app.main import app
from app.models import Base, Group, Semester
from app.models.exam import ExamEvent, ExamImport
from app.services import exams
from app.services.exam_importer import import_workbook
from tests.test_exam_parser import HEADER, book_bytes
from tests.test_session_grid_parser import grid_bytes


@pytest.fixture
def exam_db(tmp_path, bare_client):
    engine = create_engine(f"sqlite:///{tmp_path / 'exams.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        semester = Semester(title="Сессия", start_date=date(2026, 9, 1), end_date=date(2027, 1, 31),
                            total_weeks=22, first_week_parity="odd", is_active=True)
        groups = [Group(name="ИТ1-ПИб-11", course=1), Group(name="ИТ1-ПрИб-12", course=1),
                  Group(name="БИ-101", course=1), Group(name="ИТ2-БИб-21", course=2)]
        db.add_all([semester, *groups])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        yield db, semester, groups, bare_client
        app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def admin_headers():
    return {"Authorization": f"Bearer {issue_token('admin', 'admin', 1)[0]}"}


def test_import_mapping_preview_and_replacement(exam_db, tmp_path):
    db, semester, groups, _ = exam_db
    payload = book_bytes(tmp_path, [HEADER,
        ["05.10.26", None, " пи – 101 , ПрИ-102, БИ-101, БИ-201, ПИ-105", "История"],
        ["06.10.26", None, "ПИ-105", "БЖД"],
    ])
    report = import_workbook(db, payload, semester, "retake", "test.xlsx", "admin", apply=False)
    assert report.events_count == 1 and report.applied is False
    assert [m.group_id for m in report.mappings if m.group_id] == [g.id for g in groups]
    assert len(report.warnings) == 2
    assert db.scalars(select(ExamEvent)).all() == []
    assert db.scalars(select(ExamImport)).all() == []
    manual = ExamEvent(semester_id=semester.id, kind="retake", date=date(2026, 10, 1), subject="Ручное", source="manual", groups=[groups[0]])
    other = ExamEvent(semester_id=semester.id, kind="session", date=date(2026, 10, 1), subject="Сессия", source="import", groups=[groups[0]])
    old_semester = Semester(title="Старый", start_date=date(2025, 9, 1), end_date=date(2026, 1, 1), total_weeks=18, is_active=False)
    db.add_all([manual, other, old_semester]); db.flush()
    older = ExamEvent(semester_id=old_semester.id, kind="retake", date=date(2025, 10, 1), subject="Старое", source="import", groups=[groups[0]])
    db.add(older); db.commit()
    for _ in range(2):
        applied = import_workbook(db, payload, semester, "retake", "test.xlsx", "admin", apply=True)
        assert applied.events_count == 1 and applied.applied
        events = db.scalars(select(ExamEvent)).all()
        assert len(events) == 4
        assert {e.subject for e in events} == {"Ручное", "Сессия", "Старое", "История"}
        assert len(next(e for e in events if e.subject == "История").groups) == 4
    assert len(db.scalars(select(ExamImport)).all()) == 2


def test_failed_import_rolls_back_deletion(exam_db, tmp_path, monkeypatch):
    db, semester, groups, _ = exam_db
    old = ExamEvent(semester_id=semester.id, kind="retake", date=date(2026, 10, 1), subject="Старое", source="import", groups=[groups[0]])
    db.add(old); db.commit()
    payload = book_bytes(tmp_path, [HEADER, ["05.10.26", None, "ПИ-101", "История"]])
    from app.services import exam_importer
    def fail(*args, **kwargs):
        raise RuntimeError("сбой после удаления")
    monkeypatch.setattr(exam_importer, "_insert_events", fail)
    with pytest.raises(RuntimeError):
        import_workbook(db, payload, semester, "retake", "test.xlsx", "admin", apply=True)
    assert [e.subject for e in db.scalars(select(ExamEvent))] == ["Старое"]
    assert db.scalars(select(ExamImport)).all() == []


def test_admin_rights_all_routes(exam_db):
    _, _, _, client = exam_db
    student = {"Authorization": f"Bearer {issue_token('123', 'student', 1)[0]}"}
    for method, path in [("get", ""), ("get", "/imports"), ("post", "/import"),
                         ("post", ""), ("patch", "/1"), ("post", "/1/cancel"),
                         ("post", "/1/restore"), ("delete", "/1")]:
        for headers, status in [({}, 401), (student, 403)]:
            response = getattr(client, method)("/api/v1/admin/exams" + path, headers=headers)
            assert response.status_code == status, response.text


def create(client, group_ids, **fields):
    response = client.post("/api/v1/admin/exams", headers=admin_headers(), json={
        "kind": "session", "date": "2026-10-05", "start_time": "15:15", "subject": "История",
        "room": "132", "group_ids": group_ids, **fields,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_patch_first_original_and_return_to_baseline(exam_db):
    _, _, groups, client = exam_db
    item = create(client, [groups[0].id])
    path = f"/api/v1/admin/exams/{item['id']}"
    for changed in [{"date": "2026-10-06", "start_time": "16:00", "room": "122"},
                    {"date": "2026-10-07", "start_time": "17:00", "room": None}]:
        response = client.patch(path, headers=admin_headers(), json=changed)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["original"]["date"] == "2026-10-05"
        assert result["original"]["start_time"] == "15:15"
        assert result["original"]["room"] == "132"
    result = client.patch(path, headers=admin_headers(), json={"date": "2026-10-05", "start_time": "15:15", "room": "132"}).json()
    assert result["original"] is None
    for action, expected in [("cancel", True), ("restore", False)]:
        assert client.post(path + "/" + action, headers=admin_headers()).json()["cancelled"] is expected
    assert client.delete(path, headers=admin_headers()).status_code == 204
    assert client.patch(path, headers=admin_headers(), json={"subject": "Новое"}).status_code == 404


def test_student_sorted_status_dates_and_groups(exam_db, monkeypatch):
    _, _, groups, client = exam_db
    monkeypatch.setattr(exams, "today", lambda: date(2026, 10, 5))
    future = create(client, [groups[0].id, groups[1].id], date="2026-10-08", kind="retake")
    past = create(client, [groups[0].id], date="2026-10-04")
    late = create(client, [groups[0].id], start_time="17:00")
    early = create(client, [groups[0].id], start_time="11:20")
    unknown_time = create(client, [groups[0].id], start_time=None)
    client.patch(f"/api/v1/admin/exams/{future['id']}", headers=admin_headers(), json={"room": "122"})
    client.post(f"/api/v1/admin/exams/{past['id']}/cancel", headers=admin_headers())
    result = client.get(f"/api/v1/groups/{groups[0].id}/exams").json()
    assert result["kinds"] == ["session", "retake"]
    assert [e["id"] for e in result["events"]] == [past["id"], early["id"], late["id"], unknown_time["id"], future["id"]]
    first, *_, last = result["events"]
    assert first["is_past"] and first["days_left"] == -1 and first["status"] == "cancelled"
    assert last["status"] == "changed" and last["change"]["room"] == "132"
    assert last["days_left"] == 3 and not last["is_past"]
    assert last["kind"] == {"code": "retake", "name": "Пересдача"}
    assert last["groups"] == [g.name for g in groups[:2]]
    assert result["events"][1]["days_left"] == 0
    assert result["events"][1]["status"] == "regular" and result["events"][1]["change"] is None
    assert client.get("/api/v1/groups/99999/exams").status_code == 404
    assert client.get(f"/api/v1/admin/exams?kind=retake&group_id={groups[0].id}&course=1", headers=admin_headers()).json()[0]["id"] == future["id"]
    assert client.get("/api/v1/admin/exams?course=2", headers=admin_headers()).json() == []


def test_import_api_and_validation(exam_db, tmp_path):
    db, _, groups, client = exam_db
    payload = grid_bytes(tmp_path, groups=("ПИ-101",), blocks=[
        (13, "05 ОКТЯБРЯ", {2: ("ИСТОРИЯ", "(ЭКЗАМЕН)", None)}),
    ])
    for apply in [False, True]:
        response = client.post(f"/api/v1/admin/exams/import?kind=session&apply={str(apply).lower()}", headers=admin_headers(), files={"file": ("test.xlsx", payload)})
        assert response.status_code == 200, response.text
        assert response.json()["applied"] is apply
        assert response.json()["events_count"] == 1
        assert len(db.scalars(select(ExamEvent)).all()) == int(apply)
    assert len(client.get("/api/v1/admin/exams/imports", headers=admin_headers()).json()) == 1
    assert client.post("/api/v1/admin/exams/import?kind=session&apply=true", headers=admin_headers(), files={"file": ("test.xlsx", b"bad")}).status_code == 400
    assert len(db.scalars(select(ExamEvent)).all()) == 1
    for fields in [{"group_ids": []}, {"group_ids": [99999]}, {"date": None}, {"subject": " "}, {"kind": "unknown"}]:
        response = client.post("/api/v1/admin/exams", headers=admin_headers(), json={"kind": "session", "date": "2026-10-05", "subject": "История", "group_ids": [groups[0].id], **fields})
        assert response.status_code == 422, response.text

def test_imported_original_survives_manual_edits(exam_db, tmp_path):
    db, semester, groups, client = exam_db
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont

    payload = book_bytes(tmp_path, [HEADER, [
        CellRichText(TextBlock(InlineFont(strike=True), "28.09.2026"), "\n05.10.2026"),
        None, "ПИ-101", "История", None,
        CellRichText(TextBlock(InlineFont(strike=True), "132"), "\n122"),
    ]])
    import_workbook(db, payload, semester, "retake", "test.xlsx", "admin", apply=True)
    item = client.get("/api/v1/admin/exams", headers=admin_headers()).json()[0]
    path = f"/api/v1/admin/exams/{item['id']}"
    result = client.patch(path, headers=admin_headers(), json={"date": "2026-10-06", "room": "114", "subject": "История России", "group_ids": [groups[1].id]}).json()
    assert result["original"]["date"] == "2026-09-28" and result["original"]["room"] == "132"
    assert result["source"] == "import" and result["groups"][0]["id"] == groups[1].id
    result = client.patch(path, headers=admin_headers(), json={"date": "2026-09-28", "room": "132"}).json()
    assert result["original"] is None
    for data in [{"date": None}, {"group_ids": []}, {"group_ids": [99999]}, {"subject": "  "}, {"source": "manual"}]:
        assert client.patch(path, headers=admin_headers(), json=data).status_code == 422
    result = client.get("/api/v1/admin/exams", headers=admin_headers()).json()[0]
    assert result["subject"] == "История России" and result["source"] == "import"


def test_original_null_fields_and_independent_reverts(exam_db):
    db, _, groups, client = exam_db
    item = create(client, [groups[0].id], start_time=None, room=None, event_type="consultation")
    assert item["original"] is None and item["event_type"] == "consultation"
    path = f"/api/v1/admin/exams/{item['id']}"
    for changed in [{"start_time": "13:15", "room": "132"}, {"start_time": "15:15", "room": "122"}]:
        result = client.patch(path, headers=admin_headers(), json=changed).json()
        assert result["original"] == {"start_time": None, "room": None}
        db.expire_all()
        assert db.get(ExamEvent, item["id"]).original == {"start_time": None, "room": None}
    student = client.get(f"/api/v1/groups/{groups[0].id}/exams").json()["events"][0]
    assert student["type"] == {"code": "consultation", "name": "Консультация"}
    assert student["status"] == "changed"
    assert student["change"] == {"date": None, "start_time": None, "room": None, "fields": ["start_time", "room"]}
    result = client.patch(path, headers=admin_headers(), json={"start_time": None, "event_type": "exam"}).json()
    assert result["original"] == {"room": None} and result["event_type"] == "exam"
    result = client.patch(path, headers=admin_headers(), json={"room": None}).json()
    assert result["original"] is None
    assert db.scalar(select(ExamEvent.original.is_(None)).where(ExamEvent.id == item["id"]))
    assert client.get(f"/api/v1/groups/{groups[0].id}/exams").json()["events"][0]["status"] == "regular"
    assert client.patch(path, headers=admin_headers(), json={"event_type": "invalid"}).status_code == 422


@pytest.mark.parametrize("event_type,name", [("exam", "Экзамен"), ("credit", "Зачёт"),
    ("graded_credit", "Дифф. зачёт"), ("other", "Другое"), (None, None)])
def test_student_event_types(exam_db, event_type, name):
    _, _, groups, client = exam_db
    create(client, [groups[0].id], event_type=event_type)
    item = client.get(f"/api/v1/groups/{groups[0].id}/exams").json()["events"][0]
    assert item["type"] == ({"code": event_type, "name": name} if event_type else None)


def test_grid_import_routing_report_replacement_and_rollback(exam_db, tmp_path, monkeypatch):
    db, semester, groups, _ = exam_db
    payload = grid_bytes(tmp_path, groups=("ПИ-101", "ПрИ-102", "ПИ-105"), blocks=[
        (13, "15 ИЮНЯ", {column: ("БД", "(КОНСУЛЬТАЦИЯ)", "9.40, АУД. 132А") for column in (2, 3, 4)}),
    ])
    report = import_workbook(db, payload, semester, "session", "grid.xlsx", "admin")
    assert report.events_count == 1 and not report.applied
    assert report.rows[0].event_type == "consultation" and len(report.rows[0].groups) == 2
    assert report.sheets[0].academic_year == "2025-2026"
    assert report.sheets[0].groups == ["ПИ-101", "ПрИ-102", "ПИ-105"]
    assert "не найдена" in report.warnings[0].reason
    assert db.scalars(select(ExamEvent)).all() == []
    manual = create(exam_db[3], [groups[0].id], subject="Ручное")
    retake_payload = book_bytes(tmp_path, [HEADER, ["05.10.26", None, "ПИ-101", "Пересдача"]])
    import_workbook(db, retake_payload, semester, "retake", "table.xlsx", "admin", apply=True)
    for _ in range(2):
        import_workbook(db, payload, semester, "session", "grid.xlsx", "admin", apply=True)
        events = list(db.scalars(select(ExamEvent)))
        assert len(events) == 3
        assert db.get(ExamEvent, manual["id"]).source == "manual"
        assert next(e for e in events if e.kind == "retake").event_type is None
    from app.services import exam_importer
    def fail(*args, **kwargs):
        raise RuntimeError("сбой сетки")
    monkeypatch.setattr(exam_importer, "_insert_events", fail)
    with pytest.raises(RuntimeError):
        import_workbook(db, payload, semester, "session", "grid.xlsx", "admin", apply=True)
    assert len(list(db.scalars(select(ExamEvent)))) == 3
    assert len(list(db.scalars(select(ExamImport)))) == 3
