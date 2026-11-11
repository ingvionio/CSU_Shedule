from datetime import date, datetime, time
from io import BytesIO

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import UploadFile

from app.models import Base, Group, GroupHomework, HomeworkRevision, Lesson, ScheduleImport, Semester, User
from app.services import admin_imports, importer
from app.services.homework import list_homework
from app.services.weekly_importer import import_weekly
from tests.weekly_books import ONLINE, weekly_book  # noqa: F401


@pytest.fixture
def reimport_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'homework.db').as_posix()}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        db.add(Semester(title="Осень 2026", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3),
                        total_weeks=18, first_week_parity="odd", is_active=True))
        db.commit()
    yield factory
    engine.dispose()


def load(factory, paths):
    with factory() as db:
        report = import_weekly(db, [str(path) for path in paths], db.scalar(select(Semester)))
        db.commit()
        assert not report.errors
        return report


def add_homework(db, lesson, *, status="published", lesson_date=date(2026, 10, 23)):
    user = db.scalar(select(User).where(User.group_id == lesson.group_id))
    if user is None:
        user = User(full_name="Редактор Тестов", group_id=lesson.group_id)
        db.add(user)
        db.flush()
    item = GroupHomework(group_id=lesson.group_id, lesson_id=lesson.id, lesson_date=lesson_date,
                         subject_id=lesson.subject_id, title="Задачи", body="1–5", status=status,
                         due_date=date(2026, 10, 25), source="chat", version=3,
                         created_by=user.id, updated_by=user.id, updated_at=datetime(2020, 1, 2, 3, 4, 5))
    db.add(item)
    db.flush()
    return item


def snapshot(item):
    return {column.name: getattr(item, column.name) for column in GroupHomework.__table__.columns
            if column.name != "lesson_id"}


@pytest.mark.parametrize("slots,expected_slot", [([7], 7), ([8], 8), ([], None), ([5, 6], None), ([7, 8], 7)])
def test_weekly_rebind_selection(reimport_db, weekly_book, slots, expected_slot):
    original = weekly_book()
    load(reimport_db, [original])
    with reimport_db() as db:
        old = db.scalar(select(Lesson))
        item = add_homework(db, old)
        # Старый id не переиспользуется SQLite: проверяем реальную смену ссылки.
        guard_group = Group(name="ПИ 999", course=1)
        db.add(guard_group)
        db.flush()
        db.add(Lesson(semester_id=old.semester_id, group_id=guard_group.id, subject_id=old.subject_id,
                      weekday=5, start_time=time(18, 20), end_time=time(19, 50), week_parity="both",
                      valid_from=date(2026, 8, 31), lesson_type="other", status="published"))
        db.commit()
        item_id, old_id, before = item.id, item.lesson_id, snapshot(item)
    replacement = weekly_book(name="replacement.xlsx", blocks=[("ПТ", [(slot, ONLINE) for slot in slots] or [(7, [])])])
    report = load(reimport_db, [replacement])
    assert (report.homework_rebound, report.homework_unbound) == (int(expected_slot is not None), int(expected_slot is None))
    with reimport_db() as db:
        item = db.get(GroupHomework, item_id)
        assert snapshot(item) == before
        assert db.scalar(select(func.count()).select_from(HomeworkRevision)) == 0
        if expected_slot is None:
            assert item.lesson_id is None
        else:
            lesson = db.get(Lesson, item.lesson_id)
            assert lesson.slot == expected_slot and lesson.subject_id == item.subject_id
            assert lesson.import_id == report.import_id
            assert lesson.id != old_id
        _, items = list_homework(db, db.get(User, item.created_by), item.group_id, date(2026, 10, 19), date(2026, 10, 25))
        assert [entry.id for entry in items] == [item.id]


def test_double_lesson_archived_and_scope(reimport_db, weekly_book):
    eight = weekly_book(blocks=[("ПТ", [(7, ONLINE), (8, ONLINE)])])
    nine = weekly_book(name="nine.xlsx", week=9)
    other = weekly_book(name="other.xlsx", group="МБИ 101")
    load(reimport_db, [eight, nine, other])
    with reimport_db() as db:
        group_id = db.scalar(select(Group.id).where(Group.name == "МИТ 101"))
        last = db.scalar(select(Lesson).where(Lesson.group_id == group_id, Lesson.week_from == 8, Lesson.slot == 8))
        published = add_homework(db, last)
        archived = add_homework(db, last, status="archived")
        protected = [add_homework(db, lesson, lesson_date=date(2026, 10, 30) if lesson.week_from == 9 else date(2026, 10, 23))
                     for lesson in db.scalars(select(Lesson).where((Lesson.group_id != group_id) | (Lesson.week_from == 9)))]
        db.commit()
        changed = [item.id for item in [published, archived]]
        before = {item.id: (item.lesson_id, snapshot(item)) for item in protected}
    report = load(reimport_db, [eight])
    assert (report.homework_rebound, report.homework_unbound) == (2, 0)
    with reimport_db() as db:
        for item_id in changed:
            item = db.get(GroupHomework, item_id)
            assert item.lesson.slot == 8 and item.lesson.import_id == report.import_id
        for item_id, values in before.items():
            item = db.get(GroupHomework, item_id)
            assert (item.lesson_id, snapshot(item)) == values


@pytest.mark.parametrize("slots,rebound,unbound", [([7], 1, 0), ([], 0, 1)])
def test_weekly_dry_run_rolls_back(reimport_db, weekly_book, slots, rebound, unbound):
    original = weekly_book()
    load(reimport_db, [original])
    with reimport_db() as db:
        item = add_homework(db, db.scalar(select(Lesson)))
        db.commit()
        item_id, old_id, before = item.id, item.lesson_id, snapshot(item)
    replacement = weekly_book(name="new.xlsx", blocks=[("ПТ", [(slot, ONLINE) for slot in slots] or [(7, [])])])
    with reimport_db() as db:
        report = admin_imports.upload_weekly(db, [UploadFile(BytesIO(replacement.read_bytes()), filename="week.xlsx")],
                                             dry_run=True, skip_errors=False, admin="admin")
    assert not report.applied
    assert (report.homework_rebound, report.homework_unbound) == (rebound, unbound)
    with reimport_db() as db:
        item = db.get(GroupHomework, item_id)
        assert (item.lesson_id, snapshot(item)) == (old_id, before)
        assert db.scalar(select(func.count()).select_from(ScheduleImport)) == 1


@pytest.fixture
def semester_book(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "ПИ 201"
    sheet.merge_cells("C2:D2")
    sheet["C2"] = "ПИ 201"
    sheet.merge_cells("A3:A4")
    sheet["A3"] = "ПЯТНИЦА"
    sheet.merge_cells("B3:B4")
    sheet["B3"] = 7
    sheet.merge_cells("C3:D3")
    sheet["C3"] = "АЛГЕБРА (ЛЕК.)"
    sheet.merge_cells("C4:D4")
    sheet["C4"] = "ИВАНОВА О.Н., АУД. 132А"
    path = tmp_path / "semester.xlsx"
    book.save(path)
    book.close()
    return path


def test_semester_rebind_and_preview(reimport_db, semester_book):
    with reimport_db() as db:
        semester = db.scalar(select(Semester))
        importer.import_workbook(db, str(semester_book), semester)
        lesson = db.scalar(select(Lesson))
        assert lesson is not None
        item = add_homework(db, lesson)
        archived = add_homework(db, lesson, status="archived")
        db.commit()
        ids, before = [item.id, archived.id], [snapshot(item), snapshot(archived)]
        old_id = item.lesson_id
    with reimport_db() as db:
        preview = admin_imports.upload_semester(db, [UploadFile(BytesIO(semester_book.read_bytes()), filename="semester.xlsx")], True, "admin")
        assert (preview.homework_affected, preview.homework_rebound, preview.homework_unbound) == (2, 0, 0)
        assert not preview.applied and db.get(GroupHomework, ids[0]).lesson_id == old_id
    with reimport_db() as db:
        report = admin_imports.upload_semester(db, [UploadFile(BytesIO(semester_book.read_bytes()), filename="semester.xlsx")], False, "admin")
        assert report.applied
        assert (report.homework_rebound, report.homework_unbound) == (2, 0)
    with reimport_db() as db:
        for item_id, values in zip(ids, before, strict=True):
            item = db.get(GroupHomework, item_id)
            assert item.lesson.import_id == report.import_id
            assert snapshot(item) == values


@pytest.mark.parametrize("change", ["parity", "validity", "weekday", "group", "subject", "no_date"])
def test_only_matching_occurrences(reimport_db, weekly_book, monkeypatch, change):
    load(reimport_db, [weekly_book()])
    with reimport_db() as db:
        old = db.scalar(select(Lesson))
        item = add_homework(db, old, lesson_date=None if change == "no_date" else date(2026, 10, 23))
        db.commit()
        item_id = item.id
        from app.services.excel_parser import ParsedGroup, ParsedLesson, ParseResult

        parsed = ParsedLesson(group_name="МИТ 101", weekday=4 if change == "weekday" else 5,
                              slot=7, subject="ДРУГОЙ" if change == "subject" else old.subject.name,
                              lesson_type="other", parity="odd" if change == "parity" else "both",
                              teacher=None, room=None, subgroup=None,
                              week_from=9 if change == "validity" else None, week_to=None,
                              sheet="Лист", source_ref="C3", source_text="")
        if change == "group":
            parsed.group_name = "МБИ 101"
        groups = [ParsedGroup(name, 1, "Лист", 3, 4) for name in ["МИТ 101", "МБИ 101"]]
        monkeypatch.setattr(importer, "parse_workbook", lambda _: ParseResult(groups=groups, lessons=[parsed]))
        report = importer.import_workbook(db, "synthetic.xlsx", db.scalar(select(Semester)))
        assert (report.homework_rebound, report.homework_unbound) == (0, 1)
        db.expire_all()
        assert db.get(GroupHomework, item_id).lesson_id is None


@pytest.mark.parametrize("old_subgroup,new_subgroups,expected", [(2, [1, 2], 2), (None, [1], 1), (2, [1], 1)])
def test_subgroup_and_original_subject(reimport_db, weekly_book, monkeypatch, old_subgroup, new_subgroups, expected):
    from app.models import Subject
    from app.services.excel_parser import ParsedGroup, ParsedLesson, ParseResult

    load(reimport_db, [weekly_book()])
    with reimport_db() as db:
        lesson = db.scalar(select(Lesson))
        lesson.subgroup = old_subgroup
        another_subject = Subject(name="Предмет домашки")
        db.add(another_subject)
        db.flush()
        item = add_homework(db, lesson)
        item.subject_id = another_subject.id
        db.commit()
        item_id, before = item.id, snapshot(item)
        parsed = [ParsedLesson(group_name="МИТ 101", weekday=5, slot=7, subject=lesson.subject.name,
                               lesson_type="other", parity="both", teacher=None, room=None, subgroup=subgroup,
                               week_from=None, week_to=None, sheet="Лист", source_ref="C3", source_text="")
                  for subgroup in new_subgroups]
        monkeypatch.setattr(importer, "parse_workbook", lambda _: ParseResult(
            groups=[ParsedGroup("МИТ 101", 1, "Лист", 3, 4)], lessons=parsed))
        report = importer.import_workbook(db, "synthetic.xlsx", db.scalar(select(Semester)))
        assert (report.homework_rebound, report.homework_unbound) == (1, 0)
        db.expire_all()
        item = db.get(GroupHomework, item_id)
        assert item.lesson.subgroup == expected
        assert snapshot(item) == before


def test_unlinked_homework_and_append_unchanged(reimport_db, semester_book):
    with reimport_db() as db:
        semester = db.scalar(select(Semester))
        importer.import_workbook(db, str(semester_book), semester)
        item = add_homework(db, db.scalar(select(Lesson)))
        unlinked = add_homework(db, db.scalar(select(Lesson)))
        unlinked.lesson_id = None
        db.commit()
        old_id, item_id, unlinked_id = item.lesson_id, item.id, unlinked.id
        report = importer.import_workbook(db, str(semester_book), semester, replace=False)
        assert (report.homework_rebound, report.homework_unbound) == (0, 0)
        db.expire_all()
        assert db.get(GroupHomework, item_id).lesson_id == old_id
        assert db.get(GroupHomework, unlinked_id).lesson_id is None
        report = importer.import_workbook(db, str(semester_book), semester)
        assert (report.homework_rebound, report.homework_unbound) == (1, 0)
        db.expire_all()
        assert db.get(GroupHomework, unlinked_id).lesson_id is None


@pytest.mark.parametrize("kind", ["weekly", "semester"])
def test_cli_homework_counters(reimport_db, weekly_book, semester_book, monkeypatch, capsys, kind):
    from app import cli

    monkeypatch.setattr(cli, "SessionLocal", reimport_db)
    path = weekly_book() if kind == "weekly" else semester_book
    run = lambda: cli.import_weekly([str(path)]) if kind == "weekly" else cli.import_excel(str(path))
    run()
    assert "домашка:" not in capsys.readouterr().out
    with reimport_db() as db:
        add_homework(db, db.scalar(select(Lesson)))
        db.commit()
    run()
    assert "домашка: перепривязано 1, отвязано 0" in capsys.readouterr().out


def test_api_schedule_homework_key(reimport_db, weekly_book):
    from fastapi.testclient import TestClient
    from app.core.db import get_db
    from app.main import app
    from app.core.security import issue_token
    from tests.test_homework import student

    book = weekly_book()
    load(reimport_db, [book])

    def dependency():
        with reimport_db() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        with TestClient(app) as client:
            with reimport_db() as db:
                group_id = db.scalar(select(Group.id))
            user_id, headers = student(client, group_id, "Редактор Тестов", "homework-reimport-0001")
            with reimport_db() as db:
                from app.models import GroupEditor
                db.add(GroupEditor(group_id=group_id, user_id=user_id, active=True))
                lesson_id = db.scalar(select(Lesson.id))
                db.commit()
            response = client.post("/api/v1/me/homework", headers=headers, json={
                "title": "Задачи", "body": "1–5", "lesson_date": "2026-10-23", "lesson_id": lesson_id})
            assert response.status_code == 201, response.text
            admin_token, _ = issue_token("admin", "admin", 1)
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            def upload(path, dry_run):
                result = client.post("/api/v1/admin/imports/weekly", headers=admin_headers,
                                     data={"dry_run": str(dry_run).lower()},
                                     files={"files": ("week.xlsx", path.read_bytes())})
                assert result.status_code == 200, result.text
                return result.json()

            preview = upload(book, True)
            assert (preview["homework_rebound"], preview["homework_unbound"], preview["applied"]) == (1, 0, False)
            with reimport_db() as db:
                assert db.get(GroupHomework, response.json()["id"]).lesson_id == lesson_id
            applied = upload(book, False)
            assert (applied["homework_rebound"], applied["homework_unbound"], applied["applied"]) == (1, 0, True)
            listed = client.get("/api/v1/me/homework?start=2026-10-19&end=2026-10-25", headers=headers)
            assert listed.status_code == 200, listed.text
            item = listed.json()["items"][0]
            schedule = client.get(f"/api/v1/groups/{group_id}/schedule?week=8")
            assert schedule.status_code == 200, schedule.text
            keys = {f"{day['date']}:{lesson['id']}" for day in schedule.json()["days"] for lesson in day["lessons"]}
            assert f"{item['lesson_date']}:l-{item['lesson_id']}" in keys
            removed = weekly_book(name="removed.xlsx", blocks=[("ПТ", [(7, [])])])
            missing = upload(removed, False)
            assert (missing["homework_rebound"], missing["homework_unbound"]) == (0, 1)
            listed = client.get("/api/v1/me/homework?start=2026-10-19&end=2026-10-25", headers=headers).json()
            assert listed["items"][0]["id"] == item["id"] and listed["items"][0]["lesson_id"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
