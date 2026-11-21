"""Разбор таблиц сессии без базы и рабочих книг."""
from datetime import date, datetime, time

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font

from app.services.exam_parser import parse_workbook


def book_bytes(tmp_path, rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    path = tmp_path / "exams.xlsx"
    book.save(path)
    book.close()
    return path.read_bytes()


HEADER = ["Дата", "Время", "Группа", "Дисциплина", "Преподаватель", "Аудитория"]


def test_tables_headers_groups_and_excel_values(tmp_path):
    payload = book_bytes(tmp_path, [
        ["1 курс"], HEADER,
        [datetime(2026, 9, 22), time(13, 15), "ПрИ-101,102,103", "История\n России", " Иванов  И.И. ", "122\n2 корпус\nЗаранее зайти за ведомостью"],
        [], ["22.09.26", "13.15", "ПрИ-101, 102", "БЖД"],
        [" АУД. ", " дисциплина ", "ГРУППЫ", "Время", "Дата", "Преподаватель"],
        ["онлайн", "Ин.язык", "БИ-101, ПИ-101", None, "02.10.2026", "Ткач Е.С."],
        [None, "Без даты", "ПИ-101"],
    ])
    parsed = parse_workbook(payload)
    assert len(parsed.rows) == 3
    first, second, third = parsed.rows
    assert first.date == date(2026, 9, 22) and first.start_time == time(13, 15)
    assert first.groups == ["ПрИ-101", "ПрИ-102", "ПрИ-103"]
    assert second.groups == ["ПрИ-101", "ПрИ-102"]
    assert third.groups == ["БИ-101", "ПИ-101"] and third.start_time is None
    assert first.subject == "История России" and first.teacher == "Иванов И.И."
    assert first.room == "122, 2 корпус" and first.note == "Заранее зайти за ведомостью"
    assert len(parsed.warnings) == 1 and "не разобрано" in parsed.warnings[0].reason


def test_rich_strike_and_whole_cell_strike(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(HEADER)
    sheet.append([CellRichText(TextBlock(InlineFont(strike=True), "28.09.2026"), "\n05.10.2026"),
                  CellRichText(TextBlock(InlineFont(strike=True), "13:15"), "\n15:15"),
                  "ПИ-101", "Информатика", "Николаев", 
                  CellRichText(TextBlock(InlineFont(strike=True), "132"), "\n132а\nВнимание! Получить задание!!!")])
    sheet.append([date(2026, 10, 2), time(11, 20), "БИ-101", "БЖД", None, "307 (11 корпус)"])
    sheet.cell(3, 6).font = Font(strike=True)
    sheet.append(["12.10.2026", None, "БИ-101", "История"])
    sheet.cell(4, 1).font = Font(strike=True)
    other = book.create_sheet("2 курс")
    other.append(HEADER)
    other.append(["12.10.26", "11:20", "БИ-201", "БЖД"])
    path = tmp_path / "strike.xlsx"
    book.save(path)
    book.close()
    parsed = parse_workbook(path.read_bytes())
    first, second, third = parsed.rows
    assert (first.date, first.original["date"]) == (date(2026, 10, 5), "2026-09-28")
    assert (first.start_time, first.original["start_time"]) == (time(15, 15), "13:15")
    assert (first.room, first.original["room"]) == ("132а", "132")
    assert first.note == "Внимание! Получить задание!!!"
    assert second.room is None and second.original["room"] == "307 (11 корпус)"
    assert third.sheet == "2 курс"
    assert len(parsed.warnings) == 1


def test_invalid_values_are_reported_without_silent_truncation(tmp_path):
    parsed = parse_workbook(book_bytes(tmp_path, [HEADER,
        ["31.02.2026", None, "ПИ-101", "История"],
        ["01.10.26", "25:99", "ПИ-101", "История"],
        ["01.10.26", None, "ПИ-101", "x" * 301],
    ]))
    assert parsed.rows == []
    assert len(parsed.warnings) == 3
