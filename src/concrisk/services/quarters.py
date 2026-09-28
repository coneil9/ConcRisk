import re
from datetime import date

_QUARTER_RE = re.compile(r"^(\d{4})[-_]?[Qq]([1-4])$")
_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_END_DAY = {1: 31, 2: 30, 3: 30, 4: 31}


def parse_quarter(s: str) -> date:
    """`"2026Q1"` → `date(2026, 3, 31)`. Accepts 2026Q1, 2026q1, 2026-Q1."""
    m = _QUARTER_RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid quarter string: {s!r} (expected e.g. 2026Q1)")
    year = int(m.group(1))
    q = int(m.group(2))
    return date(year, _END_MONTH[q], _END_DAY[q])


def format_quarter(d: date) -> str:
    """`date(2026, 6, 30)` → `"2026Q2"`."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}"
