from datetime import date, datetime, time
from io import BytesIO

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import UploadFile

from app.models import Base, Group, GroupHomework, HomeworkRevision, Lesson, ScheduleImport, Semester, User
from app.services import admin_imports, importer
from app.services.homework import list_homework
from app.services.weekly_importer import import_weekly
from tests.weekly_books import ONLINE, weekly_book  # noqa: F401


@pytest.fixture
async def reimport_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'homework.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as db:
        db.add(Semester(title="Осень 2026", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3),
                        total_weeks=18, first_week_parity="odd", is_active=True))
        await db.commit()
    yield factory
    await engine.dispose()


async def load(factory, paths):
    async with factory() as db:
        report = await import_weekly(db, [str(path) for path in paths], await db.scalar(select(Semester)))
        await db.commit()
        assert not report.errors
        return report


async def add_homework(db, lesson, *, status="published", lesson_date=date(2026, 10, 23)):
    user = await db.scalar(select(User).where(User.group_id == lesson.group_id))
    if user is None:
        user = User(full_name="Редактор Тестов", group_id=lesson.group_id)
        db.add(user)
        await db.flush()
    item = GroupHomework(group_id=lesson.group_id, lesson_id=lesson.id, lesson_date=lesson_date,
                         subject_id=lesson.subject_id, title="Задачи", body="1–5", status=status,
                         due_date=date(2026, 10, 25), source="chat", version=3,
                         created_by=user.id, updated_by=user.id, updated_at=datetime(2020, 1, 2, 3, 4, 5))
    db.add(item)
    await db.flush()
    return item


def snapshot(item):
    return {column.name: getattr(item, column.name) for column in GroupHomework.__table__.columns
            if column.name != "lesson_id"}


@pytest.mark.parametrize("slots,expected_slot", [([7], 7), ([8], 8), ([], None), ([5, 6], None), ([7, 8], 7)])
async def test_weekly_rebind_selection(reimport_db, weekly_book, slots, expected_slot):
    original = weekly_book()
    await load(reimport_db, [original])
    async with reimport_db() as db:
        old = await db.scalar(select(Lesson))
        item = await add_homework(db, old)
        # Старый id не переиспользуется SQLite: проверяем реальную смену ссылки.
        guard_group = Group(name="ПИ 999", course=1)
        db.add(guard_group)
        await db.flush()
        db.add(Lesson(semester_id=old.semester_id, group_id=guard_group.id, subject_id=old.subject_id,
                      weekday=5, start_time=time(18, 20), end_time=time(19, 50), week_parity="both",
                      valid_from=date(2026, 8, 31), lesson_type="other", status="published"))
        await db.commit()
        item_id, old_id, before = item.id, item.lesson_id, snapshot(item)
    replacement = weekly_book(name="replacement.xlsx", blocks=[("ПТ", [(slot, ONLINE) for slot in slots] or [(7, [])])])
    report = await load(reimport_db, [replacement])
    assert (report.homework_rebound, report.homework_unbound) == (int(expected_slot is not None), int(expected_slot is None))
    async with reimport_db() as db:
        item = await db.get(GroupHomework, item_id)
        assert snapshot(item) == before
        assert await db.scalar(select(func.count()).select_from(HomeworkRevision)) == 0
        if expected_slot is None:
            assert item.lesson_id is None
        else:
            lesson = await db.get(Lesson, item.lesson_id)
            assert lesson.slot == expected_slot and lesson.subject_id == item.subject_id
            assert lesson.import_id == report.import_id
            assert lesson.id != old_id
        _, items = await list_homework(db, await db.get(User, item.created_by), item.group_id, date(2026, 10, 19), date(2026, 10, 25))
        assert [entry.id for entry in items] == [item.id]


async def test_double_lesson_archived_and_scope(reimport_db, weekly_book):
    eight = weekly_book(blocks=[("ПТ", [(7, ONLINE), (8, ONLINE)])])
    nine = weekly_book(name="nine.xlsx", week=9)
    other = weekly_book(name="other.xlsx", group="МБИ 101")
    await load(reimport_db, [eight, nine, other])
    async with reimport_db() as db:
        group_id = await db.scalar(select(Group.id).where(Group.name == "МИТ 101"))
        last = await db.scalar(select(Lesson).where(Lesson.group_id == group_id, Lesson.week_from == 8, Lesson.slot == 8))
        published = await add_homework(db, last)
        archived = await add_homework(db, last, status="archived")
        protected = [await add_homework(db, lesson, lesson_date=date(2026, 10, 30) if lesson.week_from == 9 else date(2026, 10, 23))
                     for lesson in await db.scalars(select(Lesson).where((Lesson.group_id != group_id) | (Lesson.week_from == 9)))]
        await db.commit()
        changed = [item.id for item in [published, archived]]
        before = {item.id: (item.lesson_id, snapshot(item)) for item in protected}
    report = await load(reimport_db, [eight])
    assert (report.homework_rebound, report.homework_unbound) == (2, 0)
    async with reimport_db() as db:
        for item_id in changed:
            item = await db.get(GroupHomework, item_id)
            assert item.lesson.slot == 8 and item.lesson.import_id == report.import_id
        for item_id, values in before.items():
            item = await db.get(GroupHomework, item_id)
            assert (item.lesson_id, snapshot(item)) == values


@pytest.mark.parametrize("slots,rebound,unbound", [([7], 1, 0), ([], 0, 1)])
async def test_weekly_dry_run_rolls_back(reimport_db, weekly_book, slots, rebound, unbound):
    original = weekly_book()
    await load(reimport_db, [original])
    async with reimport_db() as db:
        item = await add_homework(db, await db.scalar(select(Lesson)))
        await db.commit()
        item_id, old_id, before = item.id, item.lesson_id, snapshot(item)
    replacement = weekly_book(name="new.xlsx", blocks=[("ПТ", [(slot, ONLINE) for slot in slots] or [(7, [])])])
    async with reimport_db() as db:
        report = await admin_imports.upload_weekly(db, [UploadFile(BytesIO(replacement.read_bytes()), filename="week.xlsx")],
                                             dry_run=True, skip_errors=False, admin="admin")
    assert not report.applied
    assert (report.homework_rebound, report.homework_unbound) == (rebound, unbound)
    async with reimport_db() as db:
        item = await db.get(GroupHomework, item_id)
        assert (item.lesson_id, snapshot(item)) == (old_id, before)
        assert await db.scalar(select(func.count()).select_from(ScheduleImport)) == 1


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


async def test_semester_rebind_and_preview(reimport_db, semester_book):
    async with reimport_db() as db:
        semester = await db.scalar(select(Semester))
        await importer.import_workbook(db, str(semester_book), semester)
        lesson = await db.scalar(select(Lesson))
        assert lesson is not None
        item = await add_homework(db, lesson)
        archived = await add_homework(db, lesson, status="archived")
        await db.commit()
        ids, before = [item.id, archived.id], [snapshot(item), snapshot(archived)]
        old_id = item.lesson_id
    async with reimport_db() as db:
        preview = await admin_imports.upload_semester(db, [UploadFile(BytesIO(semester_book.read_bytes()), filename="semester.xlsx")], True, "admin")
        assert (preview.homework_affected, preview.homework_rebound, preview.homework_unbound) == (2, 0, 0)
        assert not preview.applied and (await db.get(GroupHomework, ids[0])).lesson_id == old_id
    async with reimport_db() as db:
        report = await admin_imports.upload_semester(db, [UploadFile(BytesIO(semester_book.read_bytes()), filename="semester.xlsx")], False, "admin")
        assert report.applied
        assert (report.homework_rebound, report.homework_unbound) == (2, 0)
    async with reimport_db() as db:
        for item_id, values in zip(ids, before, strict=True):
            item = await db.get(GroupHomework, item_id)
            assert item.lesson.import_id == report.import_id
            assert snapshot(item) == values


@pytest.mark.parametrize("change", ["parity", "validity", "weekday", "group", "subject", "no_date"])
async def test_only_matching_occurrences(reimport_db, weekly_book, monkeypatch, change):
    await load(reimport_db, [weekly_book()])
    async with reimport_db() as db:
        old = await db.scalar(select(Lesson))
        item = await add_homework(db, old, lesson_date=None if change == "no_date" else date(2026, 10, 23))
        await db.commit()
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
        report = await importer.import_workbook(db, "synthetic.xlsx", await db.scalar(select(Semester)))
        assert (report.homework_rebound, report.homework_unbound) == (0, 1)
        db.expire_all()
        assert (await db.get(GroupHomework, item_id)).lesson_id is None


@pytest.mark.parametrize("old_subgroup,new_subgroups,expected", [(2, [1, 2], 2), (None, [1], 1), (2, [1], 1)])
async def test_subgroup_and_original_subject(reimport_db, weekly_book, monkeypatch, old_subgroup, new_subgroups, expected):
    from app.models import Subject
    from app.services.excel_parser import ParsedGroup, ParsedLesson, ParseResult

    await load(reimport_db, [weekly_book()])
    async with reimport_db() as db:
        lesson = await db.scalar(select(Lesson))
        lesson.subgroup = old_subgroup
        another_subject = Subject(name="Предмет домашки")
        db.add(another_subject)
        await db.flush()
        item = await add_homework(db, lesson)
        item.subject_id = another_subject.id
        await db.commit()
        await db.refresh(item, ["updated_at"])
        item_id, before = item.id, snapshot(item)
        parsed = [ParsedLesson(group_name="МИТ 101", weekday=5, slot=7, subject=lesson.subject.name,
                               lesson_type="other", parity="both", teacher=None, room=None, subgroup=subgroup,
                               week_from=None, week_to=None, sheet="Лист", source_ref="C3", source_text="")
                  for subgroup in new_subgroups]
        monkeypatch.setattr(importer, "parse_workbook", lambda _: ParseResult(
            groups=[ParsedGroup("МИТ 101", 1, "Лист", 3, 4)], lessons=parsed))
        report = await importer.import_workbook(db, "synthetic.xlsx", await db.scalar(select(Semester)))
        assert (report.homework_rebound, report.homework_unbound) == (1, 0)
        db.expire_all()
        item = await db.get(GroupHomework, item_id)
        assert item.lesson.subgroup == expected
        assert snapshot(item) == before


async def test_unlinked_homework_and_append_unchanged(reimport_db, semester_book):
    async with reimport_db() as db:
        semester = await db.scalar(select(Semester))
        await importer.import_workbook(db, str(semester_book), semester)
        item = await add_homework(db, await db.scalar(select(Lesson)))
        unlinked = await add_homework(db, await db.scalar(select(Lesson)))
        unlinked.lesson_id = None
        await db.commit()
        old_id, item_id, unlinked_id = item.lesson_id, item.id, unlinked.id
        report = await importer.import_workbook(db, str(semester_book), semester, replace=False)
        assert (report.homework_rebound, report.homework_unbound) == (0, 0)
        db.expire_all()
        assert (await db.get(GroupHomework, item_id)).lesson_id == old_id
        assert (await db.get(GroupHomework, unlinked_id)).lesson_id is None
        await db.refresh(semester)
        report = await importer.import_workbook(db, str(semester_book), semester)
        assert (report.homework_rebound, report.homework_unbound) == (1, 0)
        db.expire_all()
        assert (await db.get(GroupHomework, unlinked_id)).lesson_id is None


@pytest.mark.parametrize("kind", ["weekly", "semester"])
async def test_cli_homework_counters(reimport_db, weekly_book, semester_book, monkeypatch, capsys, kind):
    from app import cli

    monkeypatch.setattr(cli, "SessionLocal", reimport_db)
    path = weekly_book() if kind == "weekly" else semester_book
    async def run():
        if kind == "weekly":
            await cli.import_weekly([str(path)])
        else:
            await cli.import_excel(str(path))

    await run()
    assert "домашка:" not in capsys.readouterr().out
    async with reimport_db() as db:
        await add_homework(db, await db.scalar(select(Lesson)))
        await db.commit()
    await run()
    assert "домашка: перепривязано 1, отвязано 0" in capsys.readouterr().out


async def test_api_schedule_homework_key(reimport_db, weekly_book):
    from tests import asgi_client
    from app.core.db import get_db
    from app.main import app
    from app.core.security import issue_token
    from tests.test_homework import student

    book = weekly_book()
    await load(reimport_db, [book])

    async def dependency():
        async with reimport_db() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    try:
        async with asgi_client(app) as client:
            async with reimport_db() as db:
                group_id = await db.scalar(select(Group.id))
            user_id, headers = await student(client, group_id, "Редактор Тестов", "homework-reimport-0001")
            async with reimport_db() as db:
                from app.models import GroupEditor
                db.add(GroupEditor(group_id=group_id, user_id=user_id, active=True))
                lesson_id = await db.scalar(select(Lesson.id))
                await db.commit()
            response = await client.post("/api/v1/me/homework", headers=headers, json={
                "title": "Задачи", "body": "1–5", "lesson_date": "2026-10-23", "lesson_id": lesson_id})
            assert response.status_code == 201, response.text
            admin_token, _ = issue_token("admin", "admin", 1)
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            async def upload(path, dry_run):
                result = await client.post("/api/v1/admin/imports/weekly", headers=admin_headers,
                                     data={"dry_run": str(dry_run).lower()},
                                     files={"files": ("week.xlsx", path.read_bytes())})
                assert result.status_code == 200, result.text
                return result.json()

            preview = await upload(book, True)
            assert (preview["homework_rebound"], preview["homework_unbound"], preview["applied"]) == (1, 0, False)
            async with reimport_db() as db:
                assert (await db.get(GroupHomework, response.json()["id"])).lesson_id == lesson_id
            applied = await upload(book, False)
            assert (applied["homework_rebound"], applied["homework_unbound"], applied["applied"]) == (1, 0, True)
            listed = await client.get("/api/v1/me/homework?start=2026-10-19&end=2026-10-25", headers=headers)
            assert listed.status_code == 200, listed.text
            item = listed.json()["items"][0]
            schedule = await client.get(f"/api/v1/groups/{group_id}/schedule?week=8")
            assert schedule.status_code == 200, schedule.text
            keys = {f"{day['date']}:{lesson['id']}" for day in schedule.json()["days"] for lesson in day["lessons"]}
            assert f"{item['lesson_date']}:l-{item['lesson_id']}" in keys
            removed = weekly_book(name="removed.xlsx", blocks=[("ПТ", [(7, [])])])
            missing = await upload(removed, False)
            assert (missing["homework_rebound"], missing["homework_unbound"]) == (0, 1)
            listed = (await client.get("/api/v1/me/homework?start=2026-10-19&end=2026-10-25", headers=headers)).json()
            assert listed["items"][0]["id"] == item["id"] and listed["items"][0]["lesson_id"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
