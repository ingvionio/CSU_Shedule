"""Разбор книги с расписанием одной группы на одну неделю, без БД."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

WEEKDAYS = {"ПН": 1, "ВТ": 2, "СР": 3, "ЧТ": 4, "ПТ": 5, "СБ": 6}
WEEK_RE = re.compile(r"\s*(\d+)\s+неделя\s*", re.IGNORECASE)
DATES_RE = re.compile(r"ЗАНЯТИЯ\s+(\d{2}\.\d{2}\.\d{2}(?:\d{2})?)\s*[-–—]\s*(\d{2}\.\d{2}\.\d{2}(?:\d{2})?)", re.IGNORECASE)
GROUP_RE = re.compile(r"(?<![А-Яа-яЁё])(МПрИ|МИТ|МПИ|МБИ)[\s–—-]*(\d{3})(?!\d)", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<!\d)[1-6]\d{2}(?!\d)")
DOT_RE = re.compile(r"(?:с\s+(\d{1,2}:\d{2})\s+)?с использованием дистанционных образовательных технологий", re.IGNORECASE)
ROOM_RE = re.compile(r"АУД\.\s*(\S.*)", re.IGNORECASE)
TEACHER_RE = re.compile(r"[А-ЯЁ][А-ЯЁа-яё-]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.", re.IGNORECASE)
FREE_WORDS = {"ДЕНЬ", "САМОСТОЯТЕЛЬНЫХ", "ЗАНЯТИЙ"}


@dataclass
class WeeklyIssue:
    sheet: str
    cell: str
    text: str
    reason: str


@dataclass
class WeeklyLesson:
    weekday: int
    slot_label: int
    custom_start: str | None
    subject: str
    teacher: str
    room: str | None
    online_url: str | None
    source_ref: str
    source_text: str
    block_index: int = 0


@dataclass
class WeeklyParseResult:
    group_name: str | None = None
    course: int | None = None
    week_number: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    sheet: str = ""
    lessons: list[WeeklyLesson] = field(default_factory=list)
    errors: list[WeeklyIssue] = field(default_factory=list)
    warnings: list[WeeklyIssue] = field(default_factory=list)


def _clean(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y" if len(value) == 10 else "%d.%m.%y").date()


def parse_weekly_workbook(path: str | Path | bytes, file_name: str | None = None) -> WeeklyParseResult:
    result = WeeklyParseResult()
    name = file_name or (Path(path).name if not isinstance(path, bytes) else "")
    try:
        book = load_workbook(BytesIO(path) if isinstance(path, bytes) else path, data_only=True)
    except (OSError, ValueError, KeyError, BadZipFile, InvalidFileException, ParseError) as error:
        result.errors.append(WeeklyIssue("", "", name, f"Не удалось прочитать книгу: {error}"))
        return result

    try:
        if len(book.worksheets) != 1:
            result.errors.append(WeeklyIssue("", "", name, "В книге должен быть один лист недели"))
            return result
        sheet = book.worksheets[0]
        result.sheet = sheet.title
        week = WEEK_RE.fullmatch(sheet.title)
        if week:
            result.week_number = int(week[1])
        else:
            result.errors.append(WeeklyIssue(sheet.title, "", sheet.title, "Не найден номер недели в имени листа"))

        header_row = None
        for row in sheet.iter_rows():
            for cell in row:
                text = _clean(cell.value)
                if not re.match(r"^ЗАНЯТИЯ\b", text, re.IGNORECASE):
                    continue
                header_row = cell.row
                dates = DATES_RE.fullmatch(text)
                try:
                    if not dates:
                        raise ValueError
                    result.start_date, result.end_date = _date(dates[1]), _date(dates[2])
                    if result.end_date < result.start_date:
                        raise ValueError
                except ValueError:
                    result.errors.append(WeeklyIssue(sheet.title, cell.coordinate, text, "Не удалось разобрать даты недели"))
                break
            if header_row is not None:
                break
        if header_row is None:
            result.errors.append(WeeklyIssue(sheet.title, "", "", "Не найдена строка с датами ЗАНЯТИЯ"))

        group_text = ""
        if header_row is not None:
            group_text = next((_clean(sheet.cell(header_row + 1, col).value)
                               for col in range(3, sheet.max_column + 1)
                               if _clean(sheet.cell(header_row + 1, col).value)), "")
        number = NUMBER_RE.search(group_text)
        if number:
            result.group_name = group_text
            result.course = int(number[0][0])
        else:
            fallback = GROUP_RE.search(name)
            if fallback and fallback[2][0] in "123456":
                result.group_name = _clean(fallback[0])
                result.course = int(fallback[2][0])
            else:
                result.errors.append(WeeklyIssue(sheet.title, f"C{header_row + 1}" if header_row else "",
                                                 group_text, "Не найдена группа с трёхзначным номером в книге или имени файла"))

        days = [(area.min_row, area.max_row, WEEKDAYS[_clean(sheet.cell(area.min_row, 1).value).upper()])
                for area in sheet.merged_cells.ranges
                if area.min_col == area.max_col == 1
                and _clean(sheet.cell(area.min_row, 1).value).upper() in WEEKDAYS]
        blocks = sorted((area for area in sheet.merged_cells.ranges if area.min_col == area.max_col == 2),
                        key=lambda area: area.min_row)
        if not days or not blocks:
            result.errors.append(WeeklyIssue(sheet.title, "", "", "Не найдены объединения дней и номеров пар"))
        day_positions: dict[int, int] = {}
        for block in blocks:
            weekday = next((day for first, last, day in days if first <= block.min_row <= block.max_row <= last), None)
            if weekday is None:
                continue
            block_index = day_positions.get(weekday, 0)
            day_positions[weekday] = block_index + 1
            raw_lines = [str(sheet.cell(row, 3).value) for row in range(block.min_row, block.max_row + 1)
                         if sheet.cell(row, 3).value is not None]
            lines = [_clean(line) for line in raw_lines if _clean(line)]
            if not lines or set(" ".join(lines).upper().split()).issubset(FREE_WORDS):
                continue
            text = "\n".join(raw_lines)
            cell = f"C{block.min_row}"
            label = _clean(sheet.cell(block.min_row, 2).value)
            if not label.isdigit():
                result.errors.append(WeeklyIssue(sheet.title, f"B{block.min_row}", label, "Не удалось разобрать номер пары"))
                continue
            custom_start = online_url = room = None
            if len(lines) == 3 and ROOM_RE.fullmatch(lines[2]) and TEACHER_RE.fullmatch(lines[1]):
                subject, teacher = lines[:2]
                room = ROOM_RE.fullmatch(lines[2])[1]
            elif len(lines) == 4 and DOT_RE.fullmatch(lines[0]) and TEACHER_RE.fullmatch(lines[3]):
                custom_start = DOT_RE.fullmatch(lines[0])[1]
                online_url, subject, teacher = lines[1:]
                if custom_start is not None:
                    try:
                        custom_start = datetime.strptime(custom_start, "%H:%M").strftime("%H:%M")
                    except ValueError:
                        result.errors.append(WeeklyIssue(sheet.title, cell, text, "Некорректное время начала пары"))
                        continue
            else:
                result.warnings.append(WeeklyIssue(sheet.title, cell, text, "Нераспознанный блок пары"))
                continue
            subject = _clean(subject.replace("*", ""))
            if not subject:
                result.warnings.append(WeeklyIssue(sheet.title, cell, text, "Пустое название предмета"))
                continue
            result.lessons.append(WeeklyLesson(weekday, int(label), custom_start, subject, teacher, room,
                                               online_url, f"{sheet.title}!{cell}", text[:600], block_index))
        return result
    finally:
        book.close()
