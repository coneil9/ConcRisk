import pytest
from dashboard.formatting import money, pct


def test_pct_normal_fraction() -> None:
    # HAND-COMPUTED: 0.1234 × 100 = 12.34 → 12.3% at precision=1.
    assert pct(0.1234) == "12.3%"


def test_pct_tiny_fraction() -> None:
    assert pct(0.001) == "0.1%"


def test_pct_zero() -> None:
    assert pct(0.0) == "0.0%"


def test_pct_precision_arg() -> None:
    assert pct(0.1234, precision=3) == "12.340%"


def test_pct_none_returns_em_dash() -> None:
    assert pct(None) == "—"


def test_pct_nan_returns_em_dash() -> None:
    assert pct(float("nan")) == "—"


@pytest.mark.parametrize(
    ("dollars", "expected"),
    [
        (1_234_567_890, "$1.23B"),
        (1_000_000_000, "$1.00B"),
        (999_999_999, "$1000.00M"),  # rounds up display in M
        (1_500_000, "$1.50M"),
        (999_999, "$1000.0K"),
        (1_000, "$1.0K"),
        (999, "$999"),
        (0, "$0"),
    ],
)
def test_money_format(dollars: float, expected: str) -> None:
    # HAND-COMPUTED: divide by 1e9/1e6/1e3 threshold, precision 2/2/1/0.
    assert money(dollars) == expected


def test_money_negative() -> None:
    assert money(-1_500_000) == "-$1.50M"


def test_money_none_returns_em_dash() -> None:
    assert money(None) == "—"
