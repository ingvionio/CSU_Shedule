from datetime import date, time, timedelta
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app import cli
from app.core.db import get_db
from app.main import app
from app.models import Base, Group, Lesson, LessonOverride, ScheduleImport, Semester, Subject
from app.services.importer import ensure_reference_data, import_workbook
from app.services.weekly_importer import import_weekly
from app.services.weekly_parser import parse_weekly_workbook

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


@pytest.fixture
def weekly_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'weekly.db').as_posix()}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as db:
        db.add(Semester(title="Осень 2026", start_date=date(2026, 9, 1), end_date=date(2027, 1, 3),
                        total_weeks=18, first_week_parity="odd", is_active=True))
        db.commit()
    monkeypatch.setattr(cli, "SessionLocal", factory)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    yield factory
    app.dependency_overrides.pop(get_db)
    engine.dispose()


def load(factory, paths, skip_errors=False):
    with factory() as db:
        semester = db.scalar(select(Semester).where(Semester.is_active.is_(True)))
        report = import_weekly(db, [str(path) for path in paths], semester, skip_errors=skip_errors)
        db.commit()
        return report


def test_parser_forms_and_shifted_layout(weekly_book):
    path = weekly_book(shift=3, blocks=[
        ("ПН", [(7, ["ДЕНЬ САМОСТОЯТЕЛЬНЫХ"]), (8, ["ЗАНЯТИЙ"])]),
        ("ВТ", [(7, [])]),
        ("ПТ", [(7, ["АЛГЕБРА**", "ИВАНОВА О.Н.", "АУД. 132А"]), (8, ONLINE)]),
        ("СБ", [(3, ["с 13:10 " + DOT, URL, "АНАЛИЗ ДАННЫХ*", "ИВАНОВА О.Н."]), (4, ONLINE)]),
    ])
    result = parse_weekly_workbook(path)
    assert not result.errors and not result.warnings
    assert (result.group_name, result.course, result.week_number) == ("МИТ 101", 1, 8)
    assert (result.start_date, result.end_date) == (date(2026, 10, 19), date(2026, 10, 24))
    assert len(result.lessons) == 4
    offline, online, custom, _ = result.lessons
    assert (offline.subject, offline.room, offline.online_url) == ("АЛГЕБРА", "132А", None)
    assert (online.subject, online.room, online.online_url) == ("САМОМЕНЕДЖМЕНТ", None, URL)
    assert custom.custom_start == "13:10" and custom.weekday == 6
    assert "АНАЛИЗ ДАННЫХ*" in custom.source_text
    assert "!C" in custom.source_ref
    assert parse_weekly_workbook(path.read_bytes(), file_name=path.name).lessons == result.lessons


@pytest.mark.parametrize("header", [None, "МИТ 11", "МИТ"])
def test_group_filename_fallback(weekly_book, header):
    path = weekly_book(name="Расписание МИТ-101 1 неделя.xlsx", group=header)
    result = parse_weekly_workbook(path)
    assert result.group_name == "МИТ-101" and not result.errors
    assert parse_weekly_workbook(path.read_bytes()).errors


def test_group_header_preferred_and_spaces_collapsed(weekly_book):
    result = parse_weekly_workbook(weekly_book(name="МПИ-201.xlsx", group="  МПрИ   101  "))
    assert result.group_name == "МПрИ 101"


def test_unknown_block_warning_and_source_limit(weekly_book):
    path = weekly_book(blocks=[("ПТ", [(7, ["неизвестный блок"]),
                                        (8, [DOT, URL + "/" + "x" * 450, "ПРЕДМЕТ" * 20, "ИВАНОВА О.Н."])])])
    result = parse_weekly_workbook(path)
    assert not result.errors and len(result.warnings) == 1
    assert result.warnings[0].cell == "C7"
    assert result.warnings[0].text == "неизвестный блок"
    assert len(result.lessons[0].source_text) == 600


@pytest.mark.parametrize("slots", [(3, 4), (4, 5)])
def test_saturday_anchor_and_week_validity(weekly_db, weekly_book, slots):
    path = weekly_book(blocks=[("СБ", [(slots[0], ["с 13:10 " + DOT, URL, "ПРЕДМЕТ", "ИВАНОВА О.Н."]),
                                                 (slots[1], ONLINE)])])
    report = load(weekly_db, [path])
    assert not report.errors and report.lessons_created == 2
    with weekly_db() as db:
        lessons = db.scalars(select(Lesson).order_by(Lesson.start_time)).all()
        assert [(item.start_time, item.end_time, item.slot) for item in lessons] == [
            (time(13, 10), time(14, 40), None), (time(15), time(16, 30), 5)]
        assert all((item.week_from, item.week_to, item.week_parity, item.valid_from, item.valid_to) ==
                   (8, 8, "both", date(2026, 10, 19), date(2026, 10, 25)) for item in lessons)
        group = db.scalar(select(Group))
        assert (group.course, group.direction) == (1, "МИТ")
        group_id = group.id
    with TestClient(app) as client:
        response = client.get(f"/api/v1/groups/{group_id}/schedule?week=8")
        assert response.status_code == 200, response.text
        assert [item["online_url"] for day in response.json()["days"] for item in day["lessons"]] == [URL, URL]
        for week in [7, 9]:
            assert all(not day["lessons"] for day in client.get(f"/api/v1/groups/{group_id}/schedule?week={week}").json()["days"])


@pytest.mark.parametrize("dates", ["ЗАНЯТИЯ 12.10.26 - 17.10.26", "ЗАНЯТИЯ 32.10.26 - 33.10.26", "ЗАНЯТИЯ неизвестно"])
def test_bad_dates_prevent_writes(weekly_db, weekly_book, dates):
    report = load(weekly_db, [weekly_book(dates=dates)])
    assert report.errors
    with weekly_db() as db:
        assert db.scalar(select(func.count()).select_from(Group)) == 0
        assert db.scalar(select(func.count()).select_from(ScheduleImport)) == 0


def test_reimport_scoped_to_group_week_and_semester(weekly_db, weekly_book):
    eight = weekly_book()
    nine = weekly_book(name="nine.xlsx", week=9)
    load(weekly_db, [eight, nine])
    with weekly_db() as db:
        group = db.scalar(select(Group))
        lesson = db.scalar(select(Lesson).where(Lesson.week_from == 8))
        nine_id = db.scalar(select(Lesson.id).where(Lesson.week_from == 9))
        db.add(LessonOverride(semester_id=lesson.semester_id, group_id=group.id, lesson_id=lesson.id,
                              kind="cancel", date=date(2026, 10, 23), status="published", batch_id="cancel"))
        db.add(LessonOverride(semester_id=lesson.semester_id, group_id=group.id, kind="add",
                              date=date(2026, 10, 23), status="published", batch_id="add"))
        group.direction = "СВОЁ"
        other = Group(name="ПИ 201", course=2)
        db.add(other)
        db.flush()
        protected = Lesson(semester_id=lesson.semester_id, group_id=other.id, subject_id=lesson.subject_id,
                           weekday=5, slot=7, start_time=time(18, 20), end_time=time(19, 50),
                           week_parity="both", valid_from=date(2026, 8, 31), lesson_type="other", status="published")
        db.add(protected)
        db.commit()
        protected_id = protected.id
    report = load(weekly_db, [eight])
    assert report.overrides_deleted == 1 and report.groups_created == 0
    with weekly_db() as db:
        assert db.get(Lesson, nine_id) and db.get(Lesson, protected_id)
        assert db.scalar(select(func.count()).select_from(Lesson)) == 3
        assert db.scalar(select(func.count()).select_from(LessonOverride)) == 1
        assert db.scalar(select(Group.direction).where(Group.name == "МИТ 101")) == "СВОЁ"


@pytest.mark.parametrize("skip", [False, True])
def test_cli_atomicity_and_all_errors(weekly_db, weekly_book, tmp_path, capsys, monkeypatch, skip):
    good = weekly_book()
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not excel")
    wrong = weekly_book(name="wrong.xlsx", dates="ЗАНЯТИЯ 12.10.26 - 17.10.26")
    monkeypatch.setattr("sys.argv", ["app.cli", "import-weekly", str(good), str(broken), str(wrong)] +
                        (["--skip-errors"] if skip else []))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "broken.xlsx" in output and "wrong.xlsx" in output
    assert "Файлов: 3" in output and "ошибок: 2" in output
    with weekly_db() as db:
        assert db.scalar(select(func.count()).select_from(Lesson)) == int(skip)
        assert db.scalar(select(func.count()).select_from(Group)) == int(skip)
        assert db.scalar(select(func.count()).select_from(ScheduleImport)) == int(skip)
        if skip:
            record = db.scalar(select(ScheduleImport))
            assert len(record.errors) == 2 and record.lessons_count == 1


def test_directory_zip_and_warning_log(weekly_db, weekly_book, tmp_path):
    weekly_book(name="nested/deeper/eight.XLSX")
    warning = weekly_book(name="source.xlsx", group="МБИ 101", blocks=[("ПТ", [(7, ["неизвестно"]), (8, ONLINE)])])
    archive = tmp_path / "archive.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("каталог/расписание.xlsx", warning.read_bytes())
        zipped.writestr("../../outside.xlsx", weekly_book(name="other.xlsx", group="МПИ 101").read_bytes())
        zipped.writestr("ignore.txt", "не Excel")
    report = load(weekly_db, [tmp_path / "nested", archive])
    assert not report.errors and report.lessons_created == 3
    with weekly_db() as db:
        record = db.scalar(select(ScheduleImport))
        assert record and len(record.errors) == 1
        assert db.scalar(select(func.count()).select_from(ScheduleImport)) == 1
        assert db.scalar(select(func.count()).select_from(Lesson)) == 3
    assert not (tmp_path.parent / "outside.xlsx").exists()


def test_zip_group_fallback_uses_member_name(weekly_db, weekly_book, tmp_path):
    path = weekly_book(group="МИТ")
    archive = tmp_path / "МПИ-201.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("nested/Расписание МИТ-101 1 неделя.xlsx", path.read_bytes())
    report = load(weekly_db, [archive])
    assert not report.errors
    with weekly_db() as db:
        assert db.scalar(select(Group.name)) == "МИТ-101"


@pytest.mark.parametrize("encoding", ["cp866", "cp1251"])
def test_zip_group_fallback_legacy_encoding(weekly_db, weekly_book, tmp_path, encoding):
    class LegacyZipInfo(ZipInfo):
        def _encodeFilenameFlags(self):
            return self.filename.encode(encoding), self.flag_bits

    path = weekly_book(group="МИТ")
    archive = tmp_path / "legacy.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.writestr(LegacyZipInfo("Расписание МИТ-101.xlsx"), path.read_bytes())
    report = load(weekly_db, [archive])
    assert not report.errors
    with weekly_db() as db:
        assert db.scalar(select(Group.name)) == "МИТ-101"


def test_cli_success(weekly_db, weekly_book, capsys, monkeypatch):
    path = weekly_book()
    monkeypatch.setattr("sys.argv", ["app.cli", "import-weekly", str(path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "МИТ 101, неделя 8: пар 1" in output
    assert "Файлов: 1, групп: 1 (новых: 1), пар: 1, удалено изменений: 0, ошибок: 0" in output


def test_blocks_before_anchor_and_next_day(weekly_db, weekly_book):
    path = weekly_book(blocks=[
        ("ПТ", [(2, ONLINE), (3, ["с 13:10 " + DOT, URL, "ПРЕДМЕТ", "ИВАНОВА О.Н."]), (4, ONLINE)]),
        ("СБ", [(7, ONLINE)]),
    ])
    load(weekly_db, [path])
    with weekly_db() as db:
        assert [(item.weekday, item.slot, item.start_time) for item in db.scalars(
            select(Lesson).order_by(Lesson.weekday, Lesson.start_time))] == [
                (5, 2, time(9, 40)), (5, None, time(13, 10)), (5, 5, time(15)), (6, 7, time(18, 20))]


def test_empty_block_after_anchor_counts_in_grid(weekly_db, weekly_book):
    path = weekly_book(blocks=[("СБ", [(3, ["с 13:10 " + DOT, URL, "ПРЕДМЕТ", "ИВАНОВА О.Н."]),
                                     (4, []), (5, ONLINE)])])
    load(weekly_db, [path])
    with weekly_db() as db:
        assert [(item.slot, item.start_time) for item in db.scalars(select(Lesson).order_by(Lesson.start_time))] == [
            (None, time(13, 10)), (6, time(16, 40))]


def test_bachelor_replace_preserves_absent_groups(weekly_db, monkeypatch):
    from app.services import importer
    from app.services.excel_parser import ParsedGroup, ParseResult

    with weekly_db() as db:
        semester = db.scalar(select(Semester))
        ensure_reference_data(db)
        present, absent = Group(name="ПИ 201", course=2), Group(name="МИТ 101", course=1)
        subject = Subject(name="ПРЕДМЕТ")
        db.add_all([present, absent, subject])
        db.flush()
        for group in [present, absent]:
            db.add(Lesson(semester_id=semester.id, group_id=group.id, subject_id=subject.id,
                          weekday=1, start_time=time(8), end_time=time(9, 30), slot=1, lesson_type="other",
                          week_parity="both", valid_from=date(2026, 8, 31), status="published"))
        db.commit()
        monkeypatch.setattr(importer, "parse_workbook", lambda _: ParseResult(
            groups=[ParsedGroup(present.name, 2, "лист", 3, 4)]))
        import_workbook(db, "synthetic.xlsx", semester)
        assert db.scalar(select(func.count()).select_from(Lesson).where(Lesson.group_id == present.id)) == 0
        assert db.scalar(select(func.count()).select_from(Lesson).where(Lesson.group_id == absent.id)) == 1


def test_online_url_survives_overrides(weekly_db, weekly_book):
    load(weekly_db, [weekly_book()])
    with weekly_db() as db:
        lesson = db.scalar(select(Lesson))
        group_id = lesson.group_id
        db.add(LessonOverride(semester_id=lesson.semester_id, group_id=group_id, lesson_id=lesson.id,
                              kind="replace", date=date(2026, 10, 23), slot=7, start_time=time(18, 20),
                              end_time=time(19, 50), subject_id=lesson.subject_id, lesson_type="other", status="published", batch_id="replace"))
        db.commit()
    with TestClient(app) as client:
        def lessons(week):
            response = client.get(f"/api/v1/groups/{group_id}/schedule?week={week}")
            assert response.status_code == 200, response.text
            return [item for day in response.json()["days"] for item in day["lessons"]]

        assert lessons(8)[0]["online_url"] == URL
        with weekly_db() as db:
            override = db.scalar(select(LessonOverride))
            override.kind = "move"
            override.target_date = date(2026, 10, 26)
            db.add(LessonOverride(semester_id=lesson.semester_id, group_id=group_id, kind="add",
                                  date=date(2026, 10, 27), slot=7, start_time=time(18, 20), end_time=time(19, 50),
                                  subject_id=lesson.subject_id, lesson_type="other", status="published", batch_id="add"))
            db.commit()
        assert lessons(8)[0]["online_url"] == URL
        assert [(item["status"], item["online_url"]) for item in lessons(9)] == [("moved_in", URL), ("added", None)]
