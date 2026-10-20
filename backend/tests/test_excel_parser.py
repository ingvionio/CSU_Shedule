"""Тесты разбора ячеек Excel. Строки взяты из реального файла расписания."""

import pytest

from app.services.excel_parser import group_course, normalize_group_name, parse_lesson_text


def test_обычная_пара_с_форматом_и_аудиторией():
    result = parse_lesson_text("ИНФОРМАТИКА И ПРОГРАММИРОВАНИЕ (ЛЕК.) НИКОЛАЕВ И.Е., ДОЦЕНТ, АУД. А-13")

    assert result == {
        "subject": "ИНФОРМАТИКА И ПРОГРАММИРОВАНИЕ",
        "lesson_type": "lecture",
        "parity": "both",
        "teacher": "НИКОЛАЕВ И.Е.",
        "room": "А-13",
        "week_from": None,
        "week_to": None,
        "custom_start": None,
    }


@pytest.mark.parametrize(
    ("text", "parity"),
    [
        ("1Н. ДИСКРЕТНАЯ МАТЕМАТИКА (ЛЕК.) ЗЕМЦОВА Е.М., ДОЦЕНТ, АУД. А-17", "odd"),
        ("2Н. ИСТОРИЯ РОССИИ (ЛЕК.) РЫБАЛКО А.А., ДОЦЕНТ, АУД. А-17", "even"),
        ("ФИЛОСОФИЯ (ЛЕК.) СОЛОМКО Д.В., АУД. А-17", "both"),
    ],
)
def test_мигалка_по_префиксу(text, parity):
    assert parse_lesson_text(text)["parity"] == parity


@pytest.mark.parametrize(
    ("marker", "code"),
    [("(ЛЕК.)", "lecture"), ("(ПР.)", "practice"), ("(ЛАБ.)", "lab"), ("(ЛЕК.+ПР.)", "lecture_practice")],
)
def test_форматы_пар(marker, code):
    result = parse_lesson_text(f"ИНТЕРНЕТ-ТЕХНОЛОГИИ {marker} ГРОШЕНКО Ю.А., АУД. 132А")

    assert result["lesson_type"] == code
    assert result["subject"] == "ИНТЕРНЕТ-ТЕХНОЛОГИИ"


def test_пара_вне_сетки_звонков():
    result = parse_lesson_text("с 19:00 РАЗРАБОТКА ИНТЕРНЕТ-ПРИЛОЖЕНИЙ (ЛЕК.) ПАВЛИЧЕНКОВ Е.А., АУД. 132")

    assert result["custom_start"] == "19:00"
    assert result["subject"] == "РАЗРАБОТКА ИНТЕРНЕТ-ПРИЛОЖЕНИЙ"


def test_время_вне_сетки_перед_маркером_чётности():
    result = parse_lesson_text("с 12:00 1Н. ЗАЩИТА ИНФОРМАЦИИ (ЛЕК.) КОСЕНКО М.Ю.")

    assert result["custom_start"] == "12:00"
    assert result["parity"] == "odd"
    assert result["subject"] == "ЗАЩИТА ИНФОРМАЦИИ"


def test_ограничение_по_неделям():
    result = parse_lesson_text(
        "1Н. СОВР.ТЕХНОЛОГИИ ПОИСКА И ОБРАБОТКИ ИНФОРМАЦИИ (ЛЕК.) ЗЕМЦОВА Е.М., ДОЦЕНТ, АУД. А-15 (1-7 НЕД.)"
    )

    assert (result["week_from"], result["week_to"]) == (1, 7)
    assert result["room"] == "А-15"


def test_перенос_названия_на_вторую_строку():
    # Название не влезло в строку, преподаватель приклеен после маркера формата.
    result = parse_lesson_text(
        "МАТЕМАТИЧЕСКИЙ АНАЛИЗ. ДИФФЕРЕНЦИАЛЬНЫЕ И РАЗНОСТНЫЕ УРАВНЕНИЯ (ПР.) "
        "СОМИКОВА Т.А., АССИСТЕНТ, АУД. 432"
    )

    assert result["subject"] == "МАТЕМАТИЧЕСКИЙ АНАЛИЗ. ДИФФЕРЕНЦИАЛЬНЫЕ И РАЗНОСТНЫЕ УРАВНЕНИЯ"
    assert result["teacher"] == "СОМИКОВА Т.А."
    assert result["room"] == "432"


def test_два_преподавателя():
    result = parse_lesson_text(
        "УПРАВЛЕНИЕ ИТ-ПРОЕКТАМИ И ЖИЗНЕННЫМ ЦИКЛОМ ПО (ЛЕК.) ВОРОБЬЕВ В.И., ГНЕДКОВА Я.Е., АУД. А-21"
    )

    assert result["teacher"] == "ВОРОБЬЕВ В.И., ГНЕДКОВА Я.Е."
    assert result["room"] == "А-21"


def test_пара_без_маркера_формата():
    result = parse_lesson_text("2Н. УЧЕБНО-МЕТОДИЧЕСКИЙ МОДУЛЬ ЮРИНА Н.А., АУД. 132")

    assert result["lesson_type"] == "other"
    assert result["subject"] == "УЧЕБНО-МЕТОДИЧЕСКИЙ МОДУЛЬ"
    assert result["teacher"] == "ЮРИНА Н.А."


def test_физкультура_в_фок_без_номера_аудитории():
    result = parse_lesson_text("ФИЗИЧЕСКАЯ КУЛЬТУРА И СПОРТ (ПР.) ПАНЬКИН В.Е., ПРЕПОДАВАТЕЛЬ, ФОК")

    assert result["room"] == "ФОК"


def test_онлайн_курс_без_аудитории():
    result = parse_lesson_text("ИСТОРИЯ РОССИИ (ОНЛАЙН-КУРС 22 ЧАСА) (ЛЕК.) БЫКОВА В.В.")

    assert result["subject"] == "ИСТОРИЯ РОССИИ (ОНЛАЙН-КУРС 22 ЧАСА)"
    assert result["room"] is None
    assert result["teacher"] == "БЫКОВА В.В."


def test_пустая_ячейка_не_даёт_пару():
    assert parse_lesson_text("   ") is None


@pytest.mark.parametrize(
    ("text", "course"),
    [
        ("ИТ1-БИб-11", 1),
        ("ИТ1-ПрИб-12", 1),
        ("БИ 201", 2),
        ("ПрИ 203", 2),
        ("ПИ 301", 3),
        ("ПрИ 402", 4),
    ],
)
def test_курс_по_названию_группы(text, course):
    assert normalize_group_name(text) == text
    assert group_course(text) == course


def test_при_не_путается_с_пи():
    # Направление ПрИ должно распознаваться раньше ПИ.
    from app.services.excel_parser import GROUP_RE

    assert GROUP_RE.search("ИТ1-ПрИб-11").group(1) == "ПрИ"
    assert GROUP_RE.search("ПИ 201").group(1) == "ПИ"
