from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.core.security import issue_token
from app.main import app
from app.models import Group, Lesson, LessonOverride, ScheduleImport, Semester, Subject, TimeSlot
from tests.test_weekly_import import weekly_book, weekly_db  # noqa: F401


@pytest.fixture
def upload_client(weekly_db):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def upload_headers():
    token, _ = issue_token("admin", "admin", 1)
    return {"Authorization": f"Bearer {token}"}


def weekly_upload(client, headers, books, **data):
    return client.post("/api/v1/admin/imports/weekly", headers=headers, data=data,
                       files=[("files", (name, content)) for name, content in books])


def counts(factory):
    with factory() as db:
        return [db.scalar(select(func.count()).select_from(model))
                for model in (Group, Lesson, ScheduleImport, Subject, TimeSlot, LessonOverride)]


def add_override(factory):
    with factory() as db:
        lesson = db.scalar(select(Lesson))
        db.add(LessonOverride(semester_id=lesson.semester_id, group_id=lesson.group_id,
                              lesson_id=lesson.id, kind="cancel", date=date(2026, 10, 23),
                              batch_id="upload-test", created_by="admin"))
        db.commit()


def test_weekly_preview_apply_and_replacement(upload_client, upload_headers, weekly_db, weekly_book):
    books = [("МИТ-101.xlsx", weekly_book(group=None).read_bytes())]
    response = weekly_upload(upload_client, upload_headers, books)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["applied"] is False
    assert preview["lessons_created"] == 1 and preview["groups_created"] == 1
    assert (preview["files"][0]["group_name"], preview["files"][0]["week_number"],
            preview["files"][0]["start_date"]) == ("МИТ-101", 8, "2026-10-19")
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]

    loaded = weekly_upload(upload_client, upload_headers, books, dry_run="false").json()
    assert loaded["applied"] is True
    with weekly_db() as db:
        record = db.scalar(select(ScheduleImport))
        assert record.uploaded_by == "admin" and record.file_name == "МИТ-101.xlsx"
    add_override(weekly_db)
    before = counts(weekly_db)
    assert weekly_upload(upload_client, upload_headers, books).json()["overrides_deleted"] == 1
    assert counts(weekly_db) == before
    replaced = weekly_upload(upload_client, upload_headers, books, dry_run="false").json()
    assert replaced["overrides_deleted"] == 1 and replaced["applied"]
    assert counts(weekly_db)[:3] == [1, 1, 2]
    assert counts(weekly_db)[-1] == 0


def test_weekly_errors_are_atomic_and_can_be_skipped(upload_client, upload_headers, weekly_db, weekly_book):
    books = [("valid.xlsx", weekly_book().read_bytes()), ("broken.xlsx", b"broken")]
    result = weekly_upload(upload_client, upload_headers, books, dry_run="false").json()
    assert not result["applied"] and result["errors_count"] == 1
    assert result["files"][1]["errors"]
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]
    preview = weekly_upload(upload_client, upload_headers, books, skip_errors="true").json()
    assert preview["lessons_created"] == 1 and not preview["applied"]
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]
    result = weekly_upload(upload_client, upload_headers, books, dry_run="false", skip_errors="true").json()
    assert result["applied"] and result["lessons_created"] == 1
    with weekly_db() as db:
        record = db.scalar(select(ScheduleImport))
        assert record.uploaded_by == "admin" and len(record.errors) == 1


def test_weekly_warnings_are_reported(upload_client, upload_headers, weekly_book):
    path = weekly_book(blocks=[("ПТ", [(7, ["неизвестный блок"])])])
    result = weekly_upload(upload_client, upload_headers, [(path.name, path.read_bytes())]).json()
    assert result["errors_count"] == 0 and result["warnings_count"] == 1
    assert result["files"][0]["warnings"] == [{
        "sheet": "8 неделя", "cell": "C7", "text": "неизвестный блок", "reason": "Нераспознанный блок пары",
    }]


@pytest.mark.parametrize("name,content", [("broken.zip", b"broken"), ("empty.zip", None)])
def test_bad_or_empty_zip(upload_client, upload_headers, weekly_db, name, content):
    if content is None:
        archive = BytesIO()
        with ZipFile(archive, "w"):
            pass
        content = archive.getvalue()
    response = weekly_upload(upload_client, upload_headers, [(name, content)], dry_run="false")
    assert response.status_code == 200, response.text
    assert not response.json()["applied"] and response.json()["errors_count"] == 1
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]


def test_zip_names_and_temporary_cleanup(upload_client, upload_headers, weekly_db, weekly_book, tmp_path, monkeypatch):
    from tempfile import TemporaryDirectory
    from app.services import admin_imports

    directories = []

    def temporary(**kwargs):
        directory = TemporaryDirectory(dir=tmp_path, **kwargs)
        directories.append(directory.name)
        return directory

    monkeypatch.setattr(admin_imports, "TemporaryDirectory", temporary)
    archive = BytesIO()
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("../../МИТ-101.xlsx", weekly_book(group=None).read_bytes())
        zipped.writestr("nested/МПИ-101.xlsx", weekly_book(name="two.xlsx", group=None).read_bytes())
    result = weekly_upload(upload_client, upload_headers,
                           [("../../evil.zip", archive.getvalue()),
                            (r"C:\fakepath\МИТ-101.xlsx", weekly_book(group=None).read_bytes())]).json()
    assert result["files_count"] == 3 and not result["errors_count"]
    assert [item["file_name"] for item in result["files"]] == [
        "evil.zip!МИТ-101.xlsx", "evil.zip!МПИ-101.xlsx", "МИТ-101.xlsx"]
    from pathlib import Path
    assert directories and all(not Path(path).exists() for path in directories)
    assert not (tmp_path / "evil.zip").exists()
    assert not (tmp_path / "МИТ-101.xlsx").exists()


@pytest.mark.parametrize("endpoint,field,filename", [
    ("weekly", "files", "bad.xls"), ("semester", "file", "bad.zip"),
])
def test_invalid_extension(upload_client, upload_headers, endpoint, field, filename):
    response = upload_client.post(f"/api/v1/admin/imports/{endpoint}", headers=upload_headers,
                                  files={field: (filename, b"bad")})
    assert response.status_code == 400 and response.json()["detail"]


def test_empty_upload(upload_client, upload_headers):
    for endpoint in ("weekly", "semester"):
        response = upload_client.post(f"/api/v1/admin/imports/{endpoint}", headers=upload_headers)
        assert response.status_code == 400


def test_size_limits(upload_client, upload_headers, monkeypatch):
    from app.services import admin_imports
    monkeypatch.setattr(admin_imports, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(admin_imports, "MAX_TOTAL_BYTES", 15)
    assert weekly_upload(upload_client, upload_headers, [("one.xlsx", b"x" * 11)]).status_code == 413
    assert weekly_upload(upload_client, upload_headers,
                         [("one.xlsx", b"x" * 8), ("two.xlsx", b"x" * 8)]).status_code == 413
    assert upload_client.post("/api/v1/admin/imports/semester", headers=upload_headers,
                              files={"file": ("one.xlsx", b"x" * 11)}).status_code == 413


@pytest.mark.parametrize("path", ["/imports", "/imports/weekly", "/imports/semester"])
def test_permissions(upload_client, path):
    method = upload_client.get if path == "/imports" else upload_client.post
    assert method("/api/v1/admin" + path).status_code == 401
    token, _ = issue_token("1", "student", 1)
    assert method("/api/v1/admin" + path, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_no_active_semester(upload_client, upload_headers, weekly_db):
    with weekly_db() as db:
        db.scalar(select(Semester)).is_active = False
        db.commit()
    for endpoint, field in (("weekly", "files"), ("semester", "file")):
        response = upload_client.post(f"/api/v1/admin/imports/{endpoint}", headers=upload_headers,
                                      files={field: ("book.xlsx", b"broken")})
        assert response.status_code == 409 and "семестр" in response.json()["detail"]


@pytest.mark.parametrize("content", [b"broken", b"PK\x03\x04broken"])
def test_unreadable_semester(upload_client, upload_headers, weekly_db, content):
    for dry_run in ("true", "false"):
        response = upload_client.post("/api/v1/admin/imports/semester", headers=upload_headers,
                                      data={"dry_run": dry_run}, files={"file": ("book.xlsx", content)})
        assert response.status_code == 200, response.text
        assert not response.json()["applied"] and response.json()["errors"]
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]


def test_semester_preview_and_apply(upload_client, upload_headers, weekly_db, tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Бакалавры"
    sheet.merge_cells("C3:D3")
    sheet["C3"] = "ПИ 201"
    sheet.merge_cells("A4:A5")
    sheet["A4"] = "ПОНЕДЕЛЬНИК"
    sheet.merge_cells("B4:B5")
    sheet["B4"] = 1
    sheet.merge_cells("C4:D4")
    sheet["C4"] = "Алгебра (ЛЕК.)"
    sheet.merge_cells("C5:D5")
    sheet["C5"] = "ИВАНОВ И.И., АУД. 101"
    path = tmp_path / "semester.xlsx"
    book.save(path)
    book.close()

    def upload(dry_run):
        return upload_client.post("/api/v1/admin/imports/semester", headers=upload_headers,
                                  data={"dry_run": dry_run}, files={"file": ("semester.xlsx", path.read_bytes())})

    preview = upload("true").json()
    assert preview["groups"] == [{"name": "ПИ 201", "lessons_count": 1}]
    assert preview["lessons_replaced"] == 0 and not preview["applied"]
    assert counts(weekly_db) == [0, 0, 0, 0, 0, 0]
    assert upload("false").json()["applied"]
    with weekly_db() as db:
        assert db.scalar(select(ScheduleImport)).uploaded_by == "admin"
    add_override(weekly_db)
    before = counts(weekly_db)
    preview = upload("true").json()
    assert preview["lessons_replaced"] == 1 and preview["overrides_deleted"] == 1
    assert counts(weekly_db) == before
    assert upload("false").json()["applied"]
    assert counts(weekly_db)[-1] == 0


def test_import_history(upload_client, upload_headers, weekly_db):
    with weekly_db() as db:
        semester = db.scalar(select(Semester))
        for index in range(3):
            db.add(ScheduleImport(semester_id=semester.id, file_name=f"{index}.xlsx", status="published",
                                  lessons_count=index, uploaded_by="admin",
                                  uploaded_at=datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=index),
                                  errors=[{"severity": "error"}, {"severity": "warning"}, {"reason": "предупреждение"}]))
        db.commit()
    response = upload_client.get("/api/v1/admin/imports?limit=2", headers=upload_headers)
    assert response.status_code == 200
    assert [item["file_name"] for item in response.json()] == ["2.xlsx", "1.xlsx"]
    assert response.json()[0]["errors_count"] == 1 and response.json()[0]["warnings_count"] == 2
