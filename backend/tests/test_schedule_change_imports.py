"""Применение каждого импорта пишет уведомление, проверка не оставляет строк."""
from datetime import date
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.models import Group, Semester
from app.models.exam import ExamEvent
from app.services import admin_imports, exam_importer, schedule_changes
from tests.test_exam_parser import HEADER, book_bytes
from tests.test_session_grid_parser import grid_bytes
from tests.test_schedule_changes import DAY, db, groups, rows
from tests.weekly_books import weekly_book


def semester_bytes():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "Бакалавры"
    for cells, value in [("C3:D3", "ПИ 101"), ("A4:A5", "ПОНЕДЕЛЬНИК"), ("B4:B5", 1), ("C4:D4", "Алгебра (ЛЕК.)"), ("C5:D5", "ИВАНОВ И.И., АУД. 101")]:
        sheet.merge_cells(cells)
        sheet[cells.split(":")[0]] = value
    content = BytesIO()
    book.save(content); book.close()
    return content.getvalue()


def upload(content):
    return UploadFile(filename="schedule.xlsx", file=BytesIO(content))


def test_semester_preview_apply_and_failure(db, monkeypatch):
    content = semester_bytes()
    assert not admin_imports.upload_semester(db, [upload(content)], True, "admin").applied
    assert rows(db) == []
    assert admin_imports.upload_semester(db, [upload(content)], False, "admin").applied
    assert [(r.group_id, r.source, r.action, r.text) for r in rows(db)] == [(groups(db)[0].id, "import", "uploaded", "Расписание обновлено")]
    def fail():
        db.flush()
        raise RuntimeError("сбой импорта")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        admin_imports.upload_semester(db, [upload(content)], False, "admin")
    db.rollback()
    assert len(rows(db)) == 1


def test_weekly_preview_apply_and_batch_one_row_per_group(db, weekly_book):
    files = [weekly_book(group="МПИ 101", week=12), weekly_book(name="other.xlsx", group="МПИ 101", week=13)]
    def uploads():
        return [upload(path.read_bytes()) for path in files]
    assert not admin_imports.upload_weekly(db, uploads(), True, False, "admin").applied
    assert rows(db) == []
    assert admin_imports.upload_weekly(db, uploads(), False, False, "admin").applied
    assert len(rows(db)) == 1 and rows(db)[0].group_id == groups(db)[1].id
    assert rows(db)[0].text == "Загружено расписание на неделю 12 (16–22 ноября); Загружено расписание на неделю 13 (23–29 ноября)"


@pytest.mark.parametrize("kind", ["session", "retake"])
def test_exam_preview_apply_and_replaced_groups(db, tmp_path, kind):
    first, second = groups(db)
    second.name = "ПрИ 102"
    old = ExamEvent(semester_id=db.scalars(select(Semester)).one().id, kind=kind, date=DAY, subject="Старое", source="import", groups=[second])
    db.add(old); db.commit()
    content = (grid_bytes(tmp_path, groups=("ПИ-101",), blocks=[(13, "16 НОЯБРЯ", {2: ("АЛГЕБРА", "(ЭКЗАМЕН)", None)})])
               if kind == "session" else book_bytes(tmp_path, [HEADER, ["16.11.26", None, "ПИ-101", "Алгебра"]]))
    semester = db.scalars(select(Semester)).one()
    assert not exam_importer.import_workbook(db, content, semester, kind, "exams.xlsx", "admin").applied
    assert rows(db) == []
    assert exam_importer.import_workbook(db, content, semester, kind, "exams.xlsx", "admin", apply=True).applied
    assert {r.group_id for r in rows(db)} == {first.id, second.id}
    assert all(r.action == "uploaded" and r.source == "import" and r.text == ("Опубликовано расписание сессии" if kind == "session" else "Опубликовано расписание пересдач") for r in rows(db))


def test_failed_exam_import_rolls_back_queue_and_events(db, tmp_path, monkeypatch):
    content = book_bytes(tmp_path, [HEADER, ["16.11.26", None, "ПИ-101", "Алгебра"]])
    def fail():
        db.flush()
        raise RuntimeError("сбой")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        exam_importer.import_workbook(db, content, db.scalars(select(Semester)).one(), "retake", "exams.xlsx", "admin", apply=True)
    assert rows(db) == []
    assert list(db.scalars(select(ExamEvent))) == []
