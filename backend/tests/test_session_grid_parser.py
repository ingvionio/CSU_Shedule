"""Сетка сессии: даты, виды, регистр и зачёркивания без рабочей книги."""
from datetime import date, datetime, time

import pytest
from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font

from app.services.session_grid_parser import parse_workbook


def grid_bytes(tmp_path, *, header=True, groups=("ПИ-301", "ПрИ-301", "ПрИ-302"), blocks=None):
    book = Workbook()
    sheet = book.active
    sheet.title = "3 курс"
    sheet["D2"] = "УТВЕРЖДАЮ"
    sheet["A6"] = "Расписание промежуточной аттестации (экзаменов)"
    if header:
        sheet["A7"] = "на 6 семестр 2025 - 2026 учебного года"
    for column, group in enumerate(groups, 2):
        sheet.cell(11, column, group)
    for row, day, events in blocks or []:
        sheet.cell(row, 1, day)
        for column, lines in events.items():
            for offset, value in enumerate(lines, -1):
                sheet.cell(row + offset, column, value)
    sheet.merge_cells("A76:D76")
    sheet["A76"] = "Директор института И.И. Иванов"
    path = tmp_path / "session.xlsx"
    book.save(path)
    book.close()
    return path.read_bytes()


def test_grid_sample_types_case_and_shared_events(tmp_path):
    shared = ("УПРАВЛЕНИЕ ИТ-ПРОЕКТАМИ И ЖИЗНЕННЫМ", "ЦИКЛОМ ПО (КОНСУЛЬТАЦИЯ)",
              "ВОРОБЬЕВ В.И., ПУЩЕВ А.А., 18:00, АУД. А-13")
    parsed = parse_workbook(grid_bytes(tmp_path, blocks=[
        (13, " 15  иЮнЯ  (ПН.) ", {2: ("АРХИТЕКТУРА ПРЕДПРИЯТИЯ И МОДЕЛИРОВАНИЕ", "БИЗНЕС-ПРОЦЕССОВ (КОНСУЛЬТАЦИЯ)", "ШЕПТАЛИН А.Г., 15:00, АУД. 132А")}),
        (19, "17 ИЮНЯ", {3: ("РАЗРАБОТКА ИНТЕРНЕТ-ПРИЛОЖЕНИЙ", "(ЭКЗАМЕН)", "БОЙКО С.В., АНДРИЕВСКИЙ Л.А."),
                          4: ("SQL И БД", "(ЗАЧЕТ)", "9.40")}),
        (34, "22 ИЮНЯ (ПН.)", {2: shared, 3: shared, 4: shared}),
    ]), date(2026, 9, 1))
    assert parsed.warnings == []
    assert len(parsed.rows) == 4
    first, exam, credit, common = parsed.rows
    assert first.date == date(2026, 6, 15)
    assert first.event_type == "consultation"
    assert first.subject == "Архитектура предприятия и моделирование бизнес-процессов"
    assert first.teacher == "Шепталин А.Г." and first.room == "132а"
    assert first.start_time == time(15)
    assert exam.event_type == "exam" and exam.start_time is exam.room is None
    assert exam.teacher == "Бойко С.В., Андриевский Л.А."
    assert credit.event_type == "credit" and credit.subject == "SQL и БД"
    assert credit.start_time == time(9, 40) and credit.teacher is None
    assert common.groups == ["ПИ-301", "ПрИ-301", "ПрИ-302"]
    assert common.subject == "Управление ИТ-проектами и жизненным циклом ПО"
    assert common.room == "А-13"
    assert parsed.sheets[0].groups == ["ПИ-301", "ПрИ-301", "ПрИ-302"]
    assert parsed.sheets[0].academic_year == "2025-2026"
    assert parsed.sheets[0].events_count == 4


@pytest.mark.parametrize("start, expected", [(date(2026, 9, 1), 2027), (date(2027, 2, 1), 2027)])
def test_fallback_academic_year_warns(tmp_path, start, expected):
    parsed = parse_workbook(grid_bytes(tmp_path, header=False, blocks=[
        (13, "01 ИЮЛЯ (СР.)", {2: ("БЖД", "(ЗАЧЁТ)", "ИВАНОВ-ПЕТРОВ И.И.")}),
        (19, "12 ДЕКАБРЯ", {2: ("ОС И ЭВМ", "(ЭКЗАМЕН)", None)}),
    ]), start)
    assert [row.date for row in parsed.rows] == [date(expected, 7, 1), date(expected - 1, 12, 12)]
    assert parsed.rows[0].teacher == "Иванов-Петров И.И."
    assert len(parsed.warnings) == 1 and "семестр" in parsed.warnings[0].reason


@pytest.mark.parametrize("label", ["ДИФФЕРЕНЦИРОВАННЫЙ ЗАЧЁТ", "ДИФФЕРЕНЦИРОВАННЫЙ ЗАЧЕТ", "ДИФ. ЗАЧЁТ", "ДИФ. ЗАЧЕТ"])
def test_december_graded_credit_and_one_line_subject(tmp_path, label):
    parsed = parse_workbook(grid_bytes(tmp_path, blocks=[
        (13, "01 ДЕКАБРЯ", {2: (None, f"МОДЕЛИРОВАНИЕ UML И 1С ({label})", "МИРАСОВ В.Ф., 19:00")}),
    ]), date(2026, 9, 1))
    row = parsed.rows[0]
    assert row.date == date(2025, 12, 1) and row.event_type == "graded_credit"
    assert row.subject == "Моделирование UML и 1С" and row.room is None


def test_other_empty_blocks_and_invalid_values(tmp_path):
    parsed = parse_workbook(grid_bytes(tmp_path, blocks=[
        (13, "15 ИЮНЯ", {2: ("ОСНОВЫ ИИ", None, "МЕДВЕДЕВ И.А.")}),
        (19, "31 ИЮНЯ", {2: ("БЖД", "(ЭКЗАМЕН)", None)}),
        (25, "20 ИЮНЯ", {2: ("БЖД", "(ЭКЗАМЕН)", "25:99")}),
        (31, "21 ИЮНЯ", {}),
    ]), date(2026, 9, 1))
    assert len(parsed.rows) == 1 and parsed.rows[0].event_type == "other"
    assert parsed.rows[0].subject == "Основы ИИ"
    assert len(parsed.warnings) == 3


def test_multiple_sheets_excel_dates_and_strikes(tmp_path):
    payload = grid_bytes(tmp_path, blocks=[
        (13, CellRichText(TextBlock(InlineFont(strike=True), "15 ИЮНЯ"), "17 ИЮНЯ"), {
            2: ("БД", "(ЭКЗАМЕН)", CellRichText("ШЕПТАЛИН А.Г., ", TextBlock(InlineFont(strike=True), "15:00, АУД. 132А"), "16:40, АУД. А-13")),
        }),
    ])
    from io import BytesIO
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(payload), rich_text=True)
    other = book.create_sheet("1 курс")
    other["A7"] = "2025 – 2026 учебного года"
    other["C11"] = "МИТ 101"
    other["A13"] = datetime(2028, 1, 20)
    other["C12"] = "БЖД"
    other["C13"] = "(ЗАЧЁТ)"
    other["C14"] = "9.40, АУД 132Б"
    other["C14"].font = Font(strike=True)
    path = tmp_path / "multi.xlsx"
    book.save(path)
    book.close()
    parsed = parse_workbook(path.read_bytes(), date(2026, 9, 1))
    first, second = parsed.rows
    assert first.original == {"date": "2026-06-15", "start_time": "15:00", "room": "132а"}
    assert first.date == date(2026, 6, 17) and first.start_time == time(16, 40) and first.room == "А-13"
    assert second.date == date(2028, 1, 20) and second.start_time is second.room is None
    assert second.original == {"start_time": "09:40", "room": "132б"}
    assert [sheet.sheet for sheet in parsed.sheets] == ["3 курс", "1 курс"]
    assert second.groups == ["МИТ 101"]


def test_room_number_struck_without_repeated_prefix(tmp_path):
    parsed = parse_workbook(grid_bytes(tmp_path, blocks=[
        (13, "15 ИЮНЯ", {2: ("БД", "(ЭКЗАМЕН)", CellRichText(
            "ШЕПТАЛИН А.Г., 15:00, АУД. ", TextBlock(InlineFont(strike=True), "132А"), "122Б"))}),
    ]), date(2026, 9, 1))
    row = parsed.rows[0]
    assert row.room == "122б" and row.original == {"room": "132а"}
    assert row.teacher == "Шепталин А.Г."
