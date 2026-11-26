"""Проверка размеров ZIP до чтения файлов расписания."""

from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile, ZipInfo

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse, parse
from openpyxl.utils.cell import range_boundaries

MIB = 1024 * 1024
MAX_WORKBOOK_BYTES = 20 * MIB
MAX_WORKSHEET_CELLS = 250_000
MAX_WORKBOOK_CELLS = 750_000
WORKSHEET_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"


class SpreadsheetArchiveError(ValueError):
    """Повреждённый архив или превышение лимита."""


def check_archive(archive: ZipFile, *, max_members: int, max_total: int, max_entry: int) -> list[ZipInfo]:
    members = archive.infolist()
    if len(members) > max_members or sum(item.file_size for item in members) > max_total:
        raise SpreadsheetArchiveError("Слишком много файлов или превышен допустимый размер распаковки")
    if any(item.file_size > max_entry or item.flag_bits & 1 for item in members):
        raise SpreadsheetArchiveError("Слишком большой или зашифрованный файл внутри архива")
    if len({item.filename for item in members}) != len(members):
        raise SpreadsheetArchiveError("В архиве есть повторяющиеся имена файлов")
    return members


def check_workbook(source: str | Path | bytes) -> None:
    try:
        with ZipFile(BytesIO(source) if isinstance(source, bytes) else source) as archive:
            members = check_archive(archive, max_members=512, max_total=64 * MIB, max_entry=24 * MIB)
            names = {item.filename for item in members if not item.is_dir()}
            if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
                raise SpreadsheetArchiveError("Файл не является книгой XLSX")
            with archive.open("[Content_Types].xml") as manifest:
                contents = parse(manifest, forbid_dtd=True).getroot()
            worksheets = {part.attrib["PartName"].lstrip("/") for part in contents
                          if part.attrib.get("ContentType") == WORKSHEET_TYPE and "PartName" in part.attrib}
            worksheets.update(name for name in names if name.startswith("xl/worksheets/") and name.endswith(".xml"))
            total_cells = 0
            for name in worksheets:
                total_cells += _worksheet_cells(archive, name)
                if total_cells > MAX_WORKBOOK_CELLS:
                    raise SpreadsheetArchiveError("Слишком много ячеек в книге расписания")
    except (BadZipFile, OSError, KeyError, ParseError, DefusedXmlException) as error:
        raise SpreadsheetArchiveError("Не удалось прочитать архив XLSX") from error


def _worksheet_cells(archive: ZipFile, name: str) -> int:
    rows = columns = explicit = merged = 0
    column_position = 0
    stack = []
    with archive.open(name) as sheet:
        for event, element in iterparse(sheet, events=("start", "end"), forbid_dtd=True):
            if event == "start":
                stack.append(element)
                continue
            tag = element.tag.rsplit("}", 1)[-1]
            reference = element.get("ref" if tag == "mergeCell" else "r")
            if tag in {"c", "mergeCell"} and reference:
                first_column, first_row, last_column, last_row = range_boundaries(reference)
                if None in (first_column, first_row, last_column, last_row):
                    raise SpreadsheetArchiveError("Недопустимый адрес ячейки в XLSX")
                if not 1 <= first_column <= last_column or not 1 <= first_row <= last_row:
                    raise SpreadsheetArchiveError("Недопустимый диапазон ячеек в XLSX")
                rows, columns = max(rows, last_row), max(columns, last_column)
                if tag == "mergeCell":
                    merged += (last_row - first_row + 1) * (last_column - first_column + 1)
                else:
                    column_position = last_column
            if tag == "c":
                explicit += 1
                if not reference:
                    column_position += 1
                    columns = max(columns, column_position)
            elif tag == "row":
                rows = max(rows, int(reference) if reference else rows + 1)
                column_position = 0
            if max(rows * columns, explicit + merged) > MAX_WORKSHEET_CELLS:
                raise SpreadsheetArchiveError("Слишком много ячеек на листе расписания")
            stack.pop()
            if stack:
                stack[-1].remove(element)
    return max(rows * columns, explicit + merged)
