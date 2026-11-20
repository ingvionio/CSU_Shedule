from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Base, Group, Semester, TimeSlot
from app.services.excel_parser import parse_workbook
from app.services.importer import import_workbook
from app.services.schedule import build_week_schedule


@pytest.fixture
def room_book(tmp_path):
    def make(room="425/201", prefix=""):
        book = Workbook()
        sheet = book.active
        sheet.title = "ПрИ-11,12"
        sheet.merge_cells("C15:D15")
        sheet["C15"] = "ИТ1-ПрИб-11"
        sheet.merge_cells("A16:A17")
        sheet["A16"] = "ПОНЕДЕЛЬНИК"
        sheet.merge_cells("B16:B17")
        sheet["B16"] = 1
        sheet.merge_cells("C16:D16")
        sheet["C16"] = prefix + "ОСНОВЫ РОССИЙСКОЙ ГОСУДАРСТВЕННОСТИ (ПР.)"
        sheet.merge_cells("C17:D17")
        sheet["C17"] = "КОРЕЦКАЯ Т.П., СТ.ПРЕП., АУД. " + room
        path = tmp_path / "schedule.xlsx"
        book.save(path)
        return path
    return make


@pytest.mark.parametrize("room,prefix,expected", [
    ("425/201", "", [("odd", "425"), ("even", "201")]),
    ("425 / 201", "", [("odd", "425"), ("even", "201")]),
    ("А-15/132Б", "", [("odd", "А-15"), ("even", "132Б")]),
    ("425/201", "1Н. ", [("odd", "425")]),
    ("425/201", "2Н. ", [("even", "201")]),
    ("А-15", "", [("both", "А-15")]),
])
def test_room_variants(room_book, room, prefix, expected):
    result = parse_workbook(str(room_book(room, prefix)))
    assert not result.errors
    assert [(item.parity, item.room) for item in result.lessons] == expected
    assert all(item.subgroup is None for item in result.lessons)
    assert all(item.teacher == "КОРЕЦКАЯ Т.П." for item in result.lessons)


async def test_import_and_schedule_choose_room_by_week(room_book, tmp_path):
    from datetime import time
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rooms.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            semester = Semester(title="Тест", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3),
                                total_weeks=18, first_week_parity="odd", is_active=True)
            db.add(semester)
            db.add(TimeSlot(number=1, start_time=time(8), end_time=time(9, 30)))
            await db.flush()
            path = str(room_book())
            await import_workbook(db, path, semester)
            await import_workbook(db, path, semester)
            group = await db.scalar(select(Group))
            for number, expected_room in [(1, "425"), (2, "201"), (3, "425")]:
                _, days = await build_week_schedule(db, group, semester, number, date(2026, 9, 2))
                lessons = [lesson for day in days for lesson in day["lessons"]]
                assert len(lessons) == 1
                assert lessons[0]["room"] == expected_room
    finally:
        await engine.dispose()
