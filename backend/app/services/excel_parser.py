"""Разбор Excel-расписания ИИТ ЧелГУ.

Чистый модуль: читает файл и возвращает структуры данных, в БД ничего не пишет.

Формат файла (по рабочему варианту на 1 семестр 2026/27):

* один лист = один курс, на листе 2-3 группы;
* строка-шапка (обычно 15-я) содержит названия групп, каждая группа занимает
  два столбца -- это подгруппы;
* столбец с днями недели (ПОНЕДЕЛЬНИК..СУББОТА), справа от него столбец
  с номерами пар; и день, и номер пары заданы вертикально объединёнными ячейками;
* внутри блока "день + номер пары" пара описана двумя идущими подряд строками:
  строка названия и строка "преподаватель, должность, АУД. номер".
  Длинное название переносится на вторую строку, и тогда преподаватель
  приклеен к ней же после маркера формата.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

WEEKDAYS: dict[str, int] = {
    "ПОНЕДЕЛЬНИК": 1,
    "ВТОРНИК": 2,
    "СРЕДА": 3,
    "ЧЕТВЕРГ": 4,
    "ПЯТНИЦА": 5,
    "СУББОТА": 6,
    "ВОСКРЕСЕНЬЕ": 7,
}

LESSON_TYPES: dict[str, str] = {
    "ЛЕК": "lecture",
    "ПР": "practice",
    "ЛАБ": "lab",
    "ЛЕК.+ПР": "lecture_practice",
    "ЛЕК+ПР": "lecture_practice",
}

# Направления подготовки. ПрИ проверяется раньше ПИ -- иначе "ПрИ" схлопнется в "ПИ".
GROUP_RE = re.compile(r"(?:ИТ\d+-)?(ПрИ|ПИ|БИ)б?[\s–—-]*(\d{2,3})", re.IGNORECASE)

# Маркер формата: (ЛЕК.), (ПР.), (ЛАБ.) и совмещённый (ЛЕК.+ПР.).
TYPE_RE = re.compile(r"\(\s*(ЛЕК\.?\s*\+\s*ПР|ЛЕК|ПР|ЛАБ)\s*\.?\s*\)", re.IGNORECASE)
PARITY_RE = re.compile(r"^\s*([12])\s*Н\.\s*", re.IGNORECASE)
# Пара вне сетки звонков: в начале ячейки стоит "с 19:00".
CUSTOM_TIME_RE = re.compile(r"^\s*с\s*(\d{1,2})[:.](\d{2})\s*", re.IGNORECASE)
WEEK_RANGE_RE = re.compile(r"\(\s*(\d{1,2})\s*[–—-]\s*(\d{1,2})\s*НЕД\.?\s*\)", re.IGNORECASE)
ROOM_RE = re.compile(r"АУД\.\s*([^,;()]+)", re.IGNORECASE)
# "ИВАНОВ И.И." / "ИВАНОВА А.С." -- фамилия и инициалы.
TEACHER_RE = re.compile(r"[А-ЯЁ][А-ЯЁа-яё-]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]?\.?")
POSITION_RE = re.compile(
    r"\b(ДОЦЕНТ|ДОЦ|ПРОФЕССОР|ПРОФ|СТ\.?\s*ПРЕП|СТАРШИЙ\s+ПРЕПОДАВАТЕЛЬ|ПРЕПОДАВАТЕЛЬ|ПРЕП|АССИСТЕНТ|АСС)\.?",
    re.IGNORECASE,
)

# Вертикальная надпись "ДЕНЬ САМОСТОЯТЕЛЬНЫХ ЗАНЯТИЙ" разложена по отдельным строкам.
FREE_DAY_WORDS = {"ДЕНЬ", "САМОСТОЯТЕЛЬНЫХ", "ЗАНЯТИЙ", "ДЕНЬ САМОСТОЯТЕЛЬНЫХ ЗАНЯТИЙ"}
# Служебные строки листа, которые не являются расписанием.
FOOTER_RE = re.compile(r"(ДИРЕКТОР ИНСТИТУТА|НАЧАЛЬНИК УПРАВЛЕНИЯ|УТВЕРЖДАЮ|ПРОРЕКТОР)", re.IGNORECASE)
SEMESTER_RE = re.compile(r"на\s+(\d{1,2})\s+семестр", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedGroup:
    name: str
    course: int
    sheet: str
    first_column: int
    last_column: int


@dataclass
class ParsedLesson:
    group_name: str
    weekday: int
    slot: int
    subject: str
    lesson_type: str
    parity: str  # odd | even | both
    teacher: str | None
    room: str | None
    subgroup: int | None
    week_from: int | None
    week_to: int | None
    sheet: str
    source_ref: str
    source_text: str
    # Время из ячейки для пары вне сетки звонков ("с 19:00"), иначе None.
    custom_start: str | None = None


@dataclass
class ParseError:
    sheet: str
    cell: str
    text: str
    reason: str


@dataclass
class ParseResult:
    groups: list[ParsedGroup] = field(default_factory=list)
    lessons: list[ParsedLesson] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    semester_number: int | None = None


def _clean(value: object) -> str:
    """Схлопывает пробелы и переносы строк внутри ячейки."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_group_name(text: str) -> str | None:
    """Приводит название группы к виду, пригодному для хранения.

    Имя сохраняется как в файле, только без лишних пробелов.
    """
    text = _clean(text)
    return text if GROUP_RE.search(text) else None


def group_course(name: str) -> int | None:
    """Курс по номеру группы: 11 -> 1, 201 -> 2, 301 -> 3, 401 -> 4."""
    match = GROUP_RE.search(name)
    if not match:
        return None
    number = match.group(2)
    course = int(number[0]) if len(number) == 3 else int(number[0])
    return course if 1 <= course <= 6 else None


class _SheetReader:
    """Доступ к ячейкам листа с учётом объединений.

    Значение объединённой области лежит в её левой верхней ячейке; остальные
    ячейки области пустые. Читаем только ячейки-источники, поэтому пара,
    объединённая на два столбца группы, попадёт в поток только один раз.
    """

    def __init__(self, sheet: Worksheet) -> None:
        self.sheet = sheet
        self.span_by_origin: dict[tuple[int, int], tuple[int, int, int, int]] = {}
        for rng in sheet.merged_cells.ranges:
            self.span_by_origin[(rng.min_row, rng.min_col)] = (
                rng.min_row,
                rng.max_row,
                rng.min_col,
                rng.max_col,
            )

    def value(self, row: int, col: int) -> str:
        return _clean(self.sheet.cell(row, col).value)

    def column_span(self, row: int, col: int) -> tuple[int, int]:
        span = self.span_by_origin.get((row, col))
        return (span[2], span[3]) if span else (col, col)

    def row_span(self, row: int, col: int) -> tuple[int, int]:
        span = self.span_by_origin.get((row, col))
        return (span[0], span[1]) if span else (row, row)


def _find_header_row(reader: _SheetReader) -> tuple[int, list[tuple[int, str]]] | None:
    """Строка с названиями групп -- та, где их встретилось больше всего."""
    best: tuple[int, list[tuple[int, str]]] | None = None
    for row in range(1, min(reader.sheet.max_row, 30) + 1):
        found = []
        for col in range(1, reader.sheet.max_column + 1):
            text = reader.value(row, col)
            if text and GROUP_RE.search(text):
                found.append((col, text))
        if found and (best is None or len(found) > len(best[1])):
            best = (row, found)
    return best


def _find_day_column(reader: _SheetReader, header_row: int) -> int | None:
    """Столбец с названиями дней недели."""
    counts: dict[int, int] = {}
    for row in range(header_row, reader.sheet.max_row + 1):
        for col in range(1, min(reader.sheet.max_column, 6) + 1):
            if reader.value(row, col).upper() in WEEKDAYS:
                counts[col] = counts.get(col, 0) + 1
    return max(counts, key=lambda col: counts[col]) if counts else None


def _day_blocks(reader: _SheetReader, day_col: int, header_row: int) -> list[tuple[int, int, int]]:
    """[(weekday, первая строка, последняя строка)] для листа."""
    starts: list[tuple[int, int, int]] = []
    for row in range(header_row, reader.sheet.max_row + 1):
        text = reader.value(row, day_col).upper()
        if text in WEEKDAYS:
            _, row_end = reader.row_span(row, day_col)
            starts.append((WEEKDAYS[text], row, row_end))

    blocks: list[tuple[int, int, int]] = []
    for index, (weekday, row_start, row_end) in enumerate(starts):
        # Объединение дня иногда короче фактического блока -- тянем до следующего дня.
        limit = starts[index + 1][1] - 1 if index + 1 < len(starts) else reader.sheet.max_row
        blocks.append((weekday, row_start, max(row_end, min(limit, reader.sheet.max_row))))
    return blocks


def _slot_blocks(reader: _SheetReader, slot_col: int, row_start: int, row_end: int) -> list[tuple[int, int, int]]:
    """[(номер пары, первая строка, последняя строка)] внутри дня."""
    found: list[tuple[int, int, int]] = []
    for row in range(row_start, row_end + 1):
        text = reader.value(row, slot_col)
        if not re.fullmatch(r"\d", text):
            continue
        _, span_end = reader.row_span(row, slot_col)
        found.append((int(text), row, span_end))

    blocks: list[tuple[int, int, int]] = []
    for index, (slot, start, span_end) in enumerate(found):
        limit = found[index + 1][1] - 1 if index + 1 < len(found) else row_end
        blocks.append((slot, start, max(span_end, min(limit, row_end))))
    return blocks


def _is_noise(text: str) -> bool:
    upper = text.upper().strip(" .,:;*")
    if not upper:
        return True
    if upper in FREE_DAY_WORDS or FOOTER_RE.search(upper):
        return True
    if text.lstrip().startswith("*"):
        return True
    # Пометки вида "с 08.10." -- примечание к паре, а не сама пара.
    if re.fullmatch(r"С\s*\d{1,2}[.\-/]\d{1,2}[.\-/]?(\d{2,4})?\.?", upper):
        return True
    return False


def parse_lesson_text(text: str) -> dict[str, object] | None:
    """Разбирает склеенный текст пары на предмет, формат, преподавателя, аудиторию."""
    # "с 19:00" стоит перед маркером чётности, поэтому разбирается первым.
    custom_start = None
    custom = CUSTOM_TIME_RE.match(text)
    if custom:
        hour, minute = int(custom.group(1)), int(custom.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            custom_start = f"{hour:02d}:{minute:02d}"
            text = text[custom.end():]

    parity = "both"
    marker = PARITY_RE.match(text)
    if marker:
        parity = "odd" if marker.group(1) == "1" else "even"
        text = text[marker.end():]

    week_from = week_to = None
    week_range = WEEK_RANGE_RE.search(text)
    if week_range:
        week_from, week_to = int(week_range.group(1)), int(week_range.group(2))
        text = WEEK_RANGE_RE.sub(" ", text)

    # Маркер формата делит строку: до него название, после -- преподаватель и аудитория.
    type_match = TYPE_RE.search(text)
    if type_match:
        marker_text = re.sub(r"\s+", "", type_match.group(1).upper()).rstrip(".")
        lesson_type = LESSON_TYPES.get(marker_text, "other")
        subject_part, rest = text[: type_match.start()], text[type_match.end():]
    else:
        # Формат не указан (например, "УЧЕБНО-МЕТОДИЧЕСКИЙ МОДУЛЬ").
        lesson_type = "other"
        teacher_match = TEACHER_RE.search(text)
        if teacher_match:
            subject_part, rest = text[: teacher_match.start()], text[teacher_match.start():]
        else:
            subject_part, rest = text, ""

    subject = re.sub(r"\s+", " ", subject_part).strip(" ,.;:-")
    if not subject:
        return None

    room = None
    room_match = ROOM_RE.search(rest)
    if room_match:
        room = room_match.group(1).strip(" .,;/-") or None
    elif re.search(r"\bФОК\b", rest, re.IGNORECASE):
        room = "ФОК"

    # Из остатка убираем аудиторию, чтобы её номер не попал в ФИО.
    names = TEACHER_RE.findall(ROOM_RE.sub(" ", rest))
    names = [name.strip() for name in names if not POSITION_RE.fullmatch(name.strip().rstrip("."))]
    teacher = ", ".join(dict.fromkeys(names)) or None

    return {
        "subject": subject,
        "lesson_type": lesson_type,
        "parity": parity,
        "teacher": teacher,
        "room": room,
        "week_from": week_from,
        "week_to": week_to,
        "custom_start": custom_start,
    }


def _column_stream(reader: _SheetReader, col: int, row_start: int, row_end: int) -> list[tuple[int, str]]:
    """Непустые ячейки одного столбца внутри блока, только ячейки-источники.

    Если область объединена на несколько столбцов, её значение принадлежит
    левому столбцу -- так пара группы не продублируется по подгруппам.
    """
    stream: list[tuple[int, str]] = []
    for row in range(row_start, row_end + 1):
        text = reader.value(row, col)
        if text and not _is_noise(text):
            stream.append((row, text))
    return stream


def _parse_group_block(
    reader: _SheetReader,
    group: ParsedGroup,
    weekday: int,
    slot: int,
    row_start: int,
    row_end: int,
    errors: list[ParseError],
) -> list[ParsedLesson]:
    """Разбирает одну клетку расписания (группа x день x номер пары)."""
    lessons: list[ParsedLesson] = []

    for offset, col in enumerate(range(group.first_column, group.last_column + 1)):
        stream = _column_stream(reader, col, row_start, row_end)
        if not stream:
            continue

        # Пара = две идущие подряд заполненные строки: название и преподаватель.
        index = 0
        while index < len(stream):
            row, first_line = stream[index]
            second_line = stream[index + 1][1] if index + 1 < len(stream) else ""
            ref = f"{get_column_letter(col)}{row}"
            combined = f"{first_line} {second_line}".strip()

            parsed = parse_lesson_text(combined)
            if parsed is None:
                errors.append(ParseError(group.sheet, ref, combined, "не удалось выделить название пары"))
                index += 2
                continue

            # Объединённая на всю группу ячейка -- пара общая, иначе это подгруппа.
            col_start, col_end = reader.column_span(row, col)
            subgroup = None if col_end > col_start else (offset + 1 if group.last_column > group.first_column else None)

            lessons.append(
                ParsedLesson(
                    group_name=group.name,
                    weekday=weekday,
                    slot=slot,
                    subject=str(parsed["subject"]),
                    lesson_type=str(parsed["lesson_type"]),
                    parity=str(parsed["parity"]),
                    teacher=parsed["teacher"],  # type: ignore[arg-type]
                    room=parsed["room"],  # type: ignore[arg-type]
                    subgroup=subgroup,
                    week_from=parsed["week_from"],  # type: ignore[arg-type]
                    week_to=parsed["week_to"],  # type: ignore[arg-type]
                    sheet=group.sheet,
                    source_ref=ref,
                    source_text=combined[:600],
                    custom_start=parsed["custom_start"],  # type: ignore[arg-type]
                )
            )
            if not second_line:
                errors.append(
                    ParseError(group.sheet, ref, first_line, "нет строки с преподавателем и аудиторией")
                )
            if len(ROOM_RE.findall(combined)) > 1:
                errors.append(
                    ParseError(
                        group.sheet,
                        ref,
                        combined,
                        "в ячейке описано несколько вариантов пары, сохранён первый",
                    )
                )
            index += 2

    return lessons


def parse_workbook(path: str | bytes) -> ParseResult:
    """Разбирает весь файл расписания."""
    workbook = load_workbook(path, data_only=True, read_only=False)
    result = ParseResult()

    for sheet in workbook.worksheets:
        reader = _SheetReader(sheet)

        header = _find_header_row(reader)
        if header is None:
            result.errors.append(ParseError(sheet.title, "-", "", "не найдена строка с названиями групп"))
            continue
        header_row, header_cells = header

        if result.semester_number is None:
            for row in range(1, header_row):
                for col in range(1, sheet.max_column + 1):
                    match = SEMESTER_RE.search(reader.value(row, col))
                    if match:
                        result.semester_number = int(match.group(1))
                        break
                if result.semester_number is not None:
                    break

        day_col = _find_day_column(reader, header_row)
        if day_col is None:
            result.errors.append(ParseError(sheet.title, "-", "", "не найден столбец с днями недели"))
            continue
        slot_col = day_col + 1

        groups: list[ParsedGroup] = []
        for col, text in header_cells:
            name = normalize_group_name(text)
            course = group_course(text) if name else None
            if not name or course is None:
                result.errors.append(
                    ParseError(sheet.title, f"{get_column_letter(col)}{header_row}", text, "не распознано название группы")
                )
                continue
            col_start, col_end = reader.column_span(header_row, col)
            groups.append(ParsedGroup(name, course, sheet.title, col_start, col_end))

        result.groups.extend(groups)

        for weekday, day_start, day_end in _day_blocks(reader, day_col, header_row):
            for slot, slot_start, slot_end in _slot_blocks(reader, slot_col, day_start, day_end):
                if not 1 <= slot <= 8:
                    continue
                for group in groups:
                    result.lessons.extend(
                        _parse_group_block(
                            reader, group, weekday, slot, slot_start, slot_end, result.errors
                        )
                    )

    workbook.close()
    return result
