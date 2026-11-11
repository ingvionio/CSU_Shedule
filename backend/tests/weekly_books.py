from datetime import date, timedelta

import pytest
from openpyxl import Workbook

DOT = "с использованием дистанционных образовательных технологий"
URL = "https://bbb.csu.ru/room"
ONLINE = [DOT, URL, "САМОМЕНЕДЖМЕНТ***", "АНТРОПОВА Л.Г."]


@pytest.fixture
def weekly_book(tmp_path):
    def make(name="week.xlsx", group="МИТ 101", week=8, blocks=None, shift=0, dates=None):
        book = Workbook()
        sheet = book.active
        sheet.title = f"{week} неделя"
        start = date(2026, 8, 31) + timedelta(weeks=week - 1)
        sheet.cell(5 + shift, 1, dates or f"ЗАНЯТИЯ {start:%d.%m.%y} - {start + timedelta(days=5):%d.%m.%y}")
        sheet.merge_cells(start_row=6 + shift, start_column=3, end_row=6 + shift, end_column=4)
        sheet.cell(6 + shift, 3, group)
        row = 7 + shift
        for day, day_blocks in (blocks or [("ПТ", [(7, ONLINE)])]):
            first = row
            for slot, lines in day_blocks:
                height = max(4, len(lines))
                sheet.merge_cells(start_row=row, start_column=2, end_row=row + height - 1, end_column=2)
                sheet.cell(row, 2, slot)
                for offset in range(height):
                    sheet.merge_cells(start_row=row + offset, start_column=3, end_row=row + offset, end_column=4)
                    if offset < len(lines):
                        sheet.cell(row + offset, 3, lines[offset])
                row += height
            sheet.merge_cells(start_row=first, start_column=1, end_row=row - 1, end_column=1)
            sheet.cell(first, 1, day)
        sheet.cell(row + 2, 1, "* занятия проходят через неделю по средам")
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        book.save(path)
        book.close()
        return path
    return make


