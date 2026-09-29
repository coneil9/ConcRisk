import math


def pct(fraction: float | None, precision: int = 1) -> str:
    """0.1234 → '12.3%'. None or NaN → '—'. CLAUDE.md: format as % only
    in the UI."""
    if fraction is None:
        return "—"
    if isinstance(fraction, float) and math.isnan(fraction):
        return "—"
    return f"{fraction * 100:.{precision}f}%"


def money(dollars: float | None) -> str:
    """1_234_567_890 → '$1.23B'. 1_000_000 → '$1.00M'. 999 → '$999'.
    None → '—'. Compact suffix formatting so $296B portfolios stay
    legible on cards."""
    if dollars is None:
        return "—"
    if isinstance(dollars, float) and math.isnan(dollars):
        return "—"
    absolute = abs(float(dollars))
    sign = "-" if dollars < 0 else ""
    if absolute >= 1_000_000_000:
        return f"{sign}${absolute / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{sign}${absolute / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{sign}${absolute / 1_000:.1f}K"
    return f"{sign}${absolute:.0f}"
