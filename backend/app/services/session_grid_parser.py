"""Чистый разбор сетки промежуточной аттестации: дата между строками события."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from io import BytesIO

from openpyxl import load_workbook
from app.services.spreadsheet_archive import check_workbook
from openpyxl.cell.cell import Cell
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.worksheet.worksheet import Worksheet

from app.services.exam_parser import ExamRow, ExamSheet, ExamWarning, ParsedExams, _parts, _time, clean, original_values

_MONTHS = {name: number for number, name in enumerate(
    ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), 1)}
_GROUP = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:\s*[-–—−]\s*|\s+)\d+")
_DAY = re.compile(r"(\d{1,2})\s+([а-яё]+)(?:\s*\([^)]*\))?", re.I)
_YEAR = re.compile(r"(\d{4})\s*[-–—−]\s*(\d{4})\s+учебного\s+года", re.I)
_TYPES = {"консультация": "consultation", "экзамен": "exam", "зачёт": "credit", "зачет": "credit",
          "дифференцированный зачёт": "graded_credit", "дифференцированный зачет": "graded_credit",
          "диф. зачёт": "graded_credit", "диф. зачет": "graded_credit"}
_ABBREVIATIONS = {"ИТ", "ИС", "БД", "СУБД", "ОС", "ЭВМ", "ИИ", "ВКР", "БЖД", "1С", "UML", "SQL", "IT"}


def _subject(value: str) -> str:
    def word(match: re.Match[str]) -> str:
        text = match[0]
        if text.upper() in _ABBREVIATIONS or re.fullmatch(r"[A-Z][A-Z\d]*", text):
            return text.upper()
        if text.upper() == "ПО" and not value[match.end():].strip():
            return "ПО"
        return text.lower()
    text = re.sub(r"[\w]+", word, value)
    return text[:1].upper() + text[1:]


def _teacher(value: str) -> str | None:
    def word(match: re.Match[str]) -> str:
        text = match[0]
        return text.upper() if len(text) == 1 and value[match.end():].startswith(".") else text.capitalize()
    return re.sub(r"[A-Za-zА-Яа-яЁё]+", word, value) or None


def _details(value: object) -> tuple[time | None, str | None, str | None]:
    start_time, room = None, None
    teachers = []
    for item in str(value or "").split(","):
        item = clean(item)
        if not item:
            continue
        if re.fullmatch(r"\d{1,2}[:.]\d{2}", item):
            start_time = _time(item)
        elif match := re.match(r"^АУД\.?\s*(.*)$", item, re.I):
            room = re.sub(r"(?<=\d)[A-Za-zА-Яа-яЁё]+", lambda m: m[0].lower(), match[1]) or None
        else:
            teachers.append(item)
    return start_time, room, _teacher(", ".join(teachers))


def _old_details(cell: Cell) -> tuple[time | None, str | None, str | None]:
    if not isinstance(cell.value, CellRichText):
        return _details(_parts(cell)[1])
    tokens: list[str] = []
    full, old = "", ""

    def append_token() -> None:
        if not clean(old):
            return
        # При зачёркивании только номера префикс аудитории остаётся общим.
        shared_prefix = re.match(r"^\s*АУД\.?", full, re.I) and not re.match(r"^\s*АУД\.?", old, re.I)
        tokens.append("АУД. " + old if shared_prefix else old)

    for fragment in cell.value:
        struck = cell.font.strike or (isinstance(fragment, TextBlock) and fragment.font.strike)
        for part in re.split(r"(,)", str(fragment)):
            if part == ",":
                append_token()
                full, old = "", ""
            else:
                full += part
                if struck:
                    old += part
    append_token()
    return _details(",".join(tokens))


def _date(value: object, years: tuple[int, int]) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DAY.fullmatch(clean(value))
    if not match or match[2].lower() not in _MONTHS:
        return None
    month = _MONTHS[match[2].lower()]
    try:
        return date(years[0] if month >= 9 else years[1], month, int(match[1]))
    except ValueError as error:
        raise ValueError("неверная дата") from error


def _parse_sheet(sheet: Worksheet, semester_start: date, result: ParsedExams) -> None:
    group_row = 0
    columns: dict[int, str] = {}
    for cells in sheet.iter_rows():
        columns = {cell.column: clean(_parts(cell)[0]) for cell in cells[1:]
                   if _GROUP.fullmatch(clean(_parts(cell)[0]))}
        if columns:
            group_row = cells[0].row
            break
    years = None
    for cells in sheet.iter_rows(max_row=group_row - 1 if group_row else sheet.max_row):
        for cell in cells:
            if match := _YEAR.search(clean(cell.value)):
                years = (int(match[1]), int(match[2]))
                break
        if years:
            break
    if years is None:
        first = semester_start.year if semester_start.month >= 9 else semester_start.year - 1
        years = (first, first + 1)
        if columns:
            result.warnings.append(ExamWarning(sheet.title, group_row, "A", "",
                "Год в шапке не найден: использован активный семестр"))
    summary = ExamSheet(sheet.title, list(columns.values()), f"{years[0]}-{years[1]}")
    result.sheets.append(summary)
    if not columns:
        result.warnings.append(ExamWarning(sheet.title, 1, "A", "", "не разобрано: строка групп не найдена"))
        return
    events: dict[tuple, ExamRow] = {}
    for row_number in range(group_row + 1, sheet.max_row + 1):
        day_cell = sheet.cell(row_number, 1)
        current, old = _parts(day_cell)
        try:
            day, old_day = _date(current, years), _date(old, years)
        except ValueError as error:
            result.warnings.append(ExamWarning(sheet.title, row_number, "A", str(day_cell.value), f"не разобрано: {error}"))
            continue
        if day is None:
            if old_day:
                result.warnings.append(ExamWarning(sheet.title, row_number, "A", str(day_cell.value), "не разобрано: нет действующей даты"))
            continue
        for column, group in columns.items():
            cells = [sheet.cell(row_number + offset, column) for offset in (-1, 0, 1)]
            parts = [_parts(cell) for cell in cells]
            if not any(clean(value) for pair in parts for value in pair):
                continue
            field_cell = cells[1]
            try:
                title_end = clean(parts[1][0])
                match = re.search(r"\(([^()]*)\)\s*$", title_end)
                event_type = _TYPES.get(clean(match[1]).lower()) if match else None
                if event_type:
                    title_end = title_end[:match.start()].strip()
                else:
                    event_type = "other"
                    result.warnings.append(ExamWarning(sheet.title, row_number, field_cell.column_letter,
                        str(field_cell.value or ""), "Вид события не найден: использован «Другое»"))
                subject = _subject(clean(f"{clean(parts[0][0])} {title_end}"))
                if not subject or len(subject) > 300:
                    raise ValueError("нет дисциплины или название длиннее 300 символов")
                field_cell = cells[2]
                start_time, room, teacher = _details(parts[2][0])
                old_time, old_room, _ = _old_details(cells[2])
                if any(len(text or "") > 200 for text in (room, old_room, teacher)):
                    raise ValueError("аудитория или преподаватель длиннее 200 символов")
                original = original_values({"date": day, "start_time": start_time, "room": room},
                                           {"date": old_day, "start_time": old_time, "room": old_room})
                key = (day, event_type, subject, teacher, start_time, room)
                if key in events:
                    if group not in events[key].groups:
                        events[key].groups.append(group)
                    continue
                events[key] = ExamRow(sheet.title, row_number, day, start_time, [group], subject, teacher, room, None,
                                      original=original, event_type=event_type, group_column=cells[1].column_letter)
            except ValueError as error:
                result.warnings.append(ExamWarning(sheet.title, row_number, field_cell.column_letter,
                                                   str(field_cell.value or ""), f"не разобрано: {error}"))
    summary.events_count = len(events)
    result.rows.extend(events.values())


def parse_workbook(payload: bytes, semester_start: date) -> ParsedExams:
    result = ParsedExams()
    check_workbook(payload)
    book = load_workbook(BytesIO(payload), rich_text=True, data_only=True)
    try:
        for sheet in book:
            _parse_sheet(sheet, semester_start, result)
    finally:
        book.close()
    return result
