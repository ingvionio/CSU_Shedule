from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app.services import spreadsheet_archive


def test_accepts_regular_workbook():
    buffer = BytesIO()
    Workbook().save(buffer)
    spreadsheet_archive.check_workbook(buffer.getvalue())


def test_rejects_zip_without_workbook_parts():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "Тест")
    with pytest.raises(spreadsheet_archive.SpreadsheetArchiveError):
        spreadsheet_archive.check_workbook(buffer.getvalue())


def test_rejects_workbook_grid_above_budget(monkeypatch):
    monkeypatch.setattr(spreadsheet_archive, "MAX_WORKSHEET_CELLS", 20)
    book = Workbook()
    book.active.merge_cells("A1:E5")
    buffer = BytesIO()
    book.save(buffer)
    with pytest.raises(spreadsheet_archive.SpreadsheetArchiveError, match="ячеек на листе"):
        spreadsheet_archive.check_workbook(buffer.getvalue())


@pytest.mark.parametrize("limits", [{"max_members": 1}, {"max_total": 10}, {"max_entry": 6}])
def test_checks_archive_limits_before_reading_entries(limits):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("first.txt", "Текст")
        archive.writestr("second.txt", "Текст")
    with ZipFile(buffer) as archive, pytest.raises(spreadsheet_archive.SpreadsheetArchiveError):
        spreadsheet_archive.check_archive(archive, **({"max_members": 2, "max_total": 100, "max_entry": 100} | limits))
