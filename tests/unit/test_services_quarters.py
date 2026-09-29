from datetime import date

import pytest

from concrisk.services import format_quarter, parse_quarter


def test_parse_quarter_q1() -> None:
    assert parse_quarter("2026Q1") == date(2026, 3, 31)


def test_parse_quarter_q4() -> None:
    assert parse_quarter("2026Q4") == date(2026, 12, 31)


def test_parse_quarter_case_insensitive() -> None:
    assert parse_quarter("2026q2") == date(2026, 6, 30)


def test_parse_quarter_dashed() -> None:
    assert parse_quarter("2026-Q3") == date(2026, 9, 30)


@pytest.mark.parametrize("bad", ["nope", "2026Q5", "202Q1", "", "2026"])
def test_parse_quarter_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_quarter(bad)


@pytest.mark.parametrize(
    ("d", "expected"),
    [
        (date(2026, 3, 31), "2026Q1"),
        (date(2026, 6, 30), "2026Q2"),
        (date(2026, 9, 30), "2026Q3"),
        (date(2026, 12, 31), "2026Q4"),
    ],
)
def test_format_quarter(d: date, expected: str) -> None:
    assert format_quarter(d) == expected
