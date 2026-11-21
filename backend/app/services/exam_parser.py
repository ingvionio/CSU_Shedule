"""Чистый разбор таблиц сессии и пересдач с сохранением зачёркиваний."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.utils import get_column_letter


@dataclass
class ExamWarning:
    sheet: str
    row: int
    column: str
    text: str
    reason: str


@dataclass
class ExamRow:
    sheet: str
    row: int
    date: date
    start_time: time | None
    groups: list[str]
    subject: str
    teacher: str | None
    room: str | None
    note: str | None
    original: dict[str, str | None] | None = None
    event_type: str | None = None
    group_column: str = ""


@dataclass
class ExamSheet:
    sheet: str
    groups: list[str]
    academic_year: str | None
    events_count: int = 0


@dataclass
class ParsedExams:
    rows: list[ExamRow] = field(default_factory=list)
    warnings: list[ExamWarning] = field(default_factory=list)
    sheets: list[ExamSheet] = field(default_factory=list)


def original_values(current: dict[str, object], old: dict[str, object]) -> dict[str, str | None] | None:
    result: dict[str, str | None] = {}
    for key, value in old.items():
        if value is not None and value != current[key]:
            result[key] = value.strftime("%H:%M") if isinstance(value, time) else value.isoformat() if isinstance(value, date) else str(value)
    return result or None


def clean(text: object) -> str:
    return " ".join(str(text).split()) if text is not None else ""


def _parts(cell: Cell) -> tuple[object, object]:
    value = cell.value
    if isinstance(value, CellRichText):
        current, old = [], []
        for fragment in value:
            struck = cell.font.strike or (isinstance(fragment, TextBlock) and fragment.font.strike)
            (old if struck else current).append(str(fragment))
        return "".join(current), "".join(old)
    return (None, value) if cell.font.strike else (value, None)


def _date(value: object) -> date | None:
    if value is None or not clean(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(clean(value), fmt).date()
        except ValueError:
            pass
    raise ValueError("неверная дата")


def _time(value: object) -> time | None:
    if value is None or not clean(value):
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", clean(value))
    if match:
        try:
            return time(int(match[1]), int(match[2]))
        except ValueError as error:
            raise ValueError("неверное время") from error
    raise ValueError("неверное время")


def parse_groups(value: object) -> list[str]:
    result: list[str] = []
    direction = ""
    for part in clean(value).split(","):
        name = re.sub(r"\s*[-–—−]\s*", "-", part.strip())
        match = re.fullmatch(r"(.+)-(\d+)", name)
        if match:
            direction = match[1]
        elif name.isdigit() and direction:
            name = f"{direction}-{name}"
        if name and name not in result:
            result.append(name)
    return result


def _room(value: object) -> tuple[str | None, str | None]:
    rooms, notes = [], []
    for line in str(value or "").splitlines():
        line = clean(line)
        if not line:
            continue
        is_room = len(line) <= 30 and (re.search(r"\d", line) or re.search(r"корпус|онлайн|ауд", line, re.I))
        (rooms if is_room else notes).append(line)
    return ", ".join(rooms) or None, " ".join(notes) or None


_HEADERS = {"дата": "date", "время": "start_time", "группа": "groups", "группы": "groups",
            "дисциплина": "subject", "преподаватель": "teacher", "аудитория": "room", "ауд.": "room", "ауд": "room"}


def parse_workbook(payload: bytes) -> ParsedExams:
    result = ParsedExams()
    book = load_workbook(BytesIO(payload), rich_text=True, data_only=True)
    try:
        for sheet in book:
            summary = ExamSheet(sheet.title, [], None)
            result.sheets.append(summary)
            columns: dict[str, int] = {}
            for cells in sheet.iter_rows():
                header = {_HEADERS[key]: index for index, cell in enumerate(cells)
                          if (key := re.sub(r"\s+", "", str(cell.value or "")).lower()) in _HEADERS}
                if len(header) == 6:
                    columns = header
                    continue
                if not columns or not any(clean(cell.value) for cell in cells):
                    continue
                values = {name: _parts(cells[index]) for name, index in columns.items()}
                current_field = "date"
                try:
                    current_date, old_date = map(_date, values["date"])
                    if current_date is None:
                        raise ValueError("нет действующей даты")
                    current_field = "subject"
                    subject = clean(values["subject"][0])
                    if not subject:
                        raise ValueError("нет дисциплины")
                    if len(subject) > 300:
                        raise ValueError("дисциплина длиннее 300 символов")
                    current_field = "start_time"
                    current_time, old_time = map(_time, values["start_time"])
                    current_field = "room"
                    room, note = _room(values["room"][0])
                    old_room, _ = _room(values["room"][1])
                    if any(len(value or "") > 200 for value in [room, old_room]):
                        raise ValueError("аудитория длиннее 200 символов")
                    current_field = "teacher"
                    teacher = clean(values["teacher"][0]) or None
                    if len(teacher or "") > 200:
                        raise ValueError("преподаватель длиннее 200 символов")
                    groups = parse_groups(values["groups"][0])
                    summary.groups.extend(name for name in groups if name not in summary.groups)
                    summary.events_count += 1
                    result.rows.append(ExamRow(
                        sheet=sheet.title, row=cells[0].row, date=current_date, start_time=current_time,
                        groups=groups, subject=subject, teacher=teacher, room=room, note=note,
                        original=original_values({"date": current_date, "start_time": current_time, "room": room},
                                                 {"date": old_date, "start_time": old_time, "room": old_room}),
                        group_column=get_column_letter(columns["groups"] + 1),
                    ))
                except ValueError as error:
                    cell = cells[columns[current_field]]
                    result.warnings.append(ExamWarning(sheet.title, cell.row, cell.column_letter,
                                                       str(cell.value or ""), f"не разобрано: {error}"))
    finally:
        book.close()
    return result
