"""Тесты календаря учебных недель."""

from datetime import date

import pytest

from app.models import Semester, WeekParity
from app.services import weeks


@pytest.fixture
def semester() -> Semester:
    # 1 сентября 2026 — вторник, значит неделя 1 начинается в понедельник 31 августа.
    return Semester(
        id=1,
        title="1 семестр 2026/27",
        start_date=date(2026, 9, 1),
        end_date=date(2027, 1, 3),
        total_weeks=18,
        first_week_parity=WeekParity.ODD.value,
        is_active=True,
    )


def test_первая_неделя_начинается_с_понедельника(semester):
    assert weeks.first_monday(semester) == date(2026, 8, 31)


def test_дата_понедельника_по_номеру_недели(semester):
    assert weeks.monday_of_week(semester, 1) == date(2026, 8, 31)
    assert weeks.monday_of_week(semester, 8) == date(2026, 10, 19)


def test_чётность_чередуется(semester):
    assert [weeks.parity_of_week(semester, n) for n in (1, 2, 3, 4)] == ["odd", "even", "odd", "even"]


def test_чётность_при_чётной_первой_неделе(semester):
    semester.first_week_parity = WeekParity.EVEN.value

    assert [weeks.parity_of_week(semester, n) for n in (1, 2, 3)] == ["even", "odd", "even"]


@pytest.mark.parametrize(
    ("day", "number"),
    [
        (date(2026, 8, 31), 1),
        (date(2026, 9, 6), 1),
        (date(2026, 9, 7), 2),
        (date(2026, 10, 20), 8),
    ],
)
def test_номер_недели_по_дате(semester, day, number):
    assert weeks.week_number_for_date(semester, day) == number


def test_дата_вне_семестра(semester):
    assert weeks.week_number_for_date(semester, date(2026, 8, 30)) is None
    assert weeks.week_number_for_date(semester, date(2027, 6, 1)) is None


def test_текущая_неделя_прижимается_к_границам(semester):
    # До начала семестра открывается первая неделя, после конца — последняя.
    assert weeks.current_week_number(semester, date(2026, 7, 1)) == 1
    assert weeks.current_week_number(semester, date(2027, 6, 1)) == 18
    assert weeks.current_week_number(semester, date(2026, 10, 20)) == 8


def test_в_воскресенье_текущая_следующая_неделя(semester):
    # 25.10.2026 — воскресенье 8-й недели.
    assert weeks.current_week_number(semester, date(2026, 10, 24)) == 8
    assert weeks.current_week_number(semester, date(2026, 10, 25)) == 9
    assert weeks.build_week_info(semester, 9, date(2026, 10, 25)).is_current is True
    # Воскресенье последней недели — следующей нет, остаётся последняя.
    assert weeks.current_week_number(semester, date(2027, 1, 3)) == 18


def test_соседние_недели_не_выходят_за_семестр(semester):
    first = weeks.build_week_info(semester, 1, date(2026, 10, 20))
    last = weeks.build_week_info(semester, 18, date(2026, 10, 20))

    assert (first.prev, first.next) == (None, 2)
    assert (last.prev, last.next) == (17, None)


def test_информация_о_неделе(semester):
    info = weeks.build_week_info(semester, 8, date(2026, 10, 20))

    assert info.number == 8
    assert info.parity == "even"
    assert info.start_date == date(2026, 10, 19)
    assert info.end_date == date(2026, 10, 25)
    assert info.is_current is True
