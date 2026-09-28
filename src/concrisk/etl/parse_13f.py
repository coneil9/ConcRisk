import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

VALUE_UNIT_DOLLARIZATION_CUTOFF = date(2023, 1, 3)
"""SEC 13F Rule Change: filings dated on or after 2023-01-03 report value
in whole dollars. Prior filings report value in thousands of dollars."""


@dataclass(frozen=True)
class CoverInfo:
    form_type: str
    period_of_report: date
    is_amendment: bool
    amendment_type: str | None  # 'RESTATEMENT' | 'NEW HOLDINGS' | None


@dataclass(frozen=True)
class ParsedPosition:
    name_of_issuer: str
    title_of_class: str
    cusip: str
    figi: str | None
    value_usd: Decimal
    shares: Decimal
    share_type: str
    put_call: str | None  # 'PUT' | 'CALL' | None
    investment_discretion: str | None


@dataclass(frozen=True)
class AggregatedPosition:
    name_of_issuer: str
    title_of_class: str
    cusip: str
    figi: str | None
    put_call: str | None
    shares: Decimal
    share_type: str
    value_usd: Decimal


class ParseError(ValueError):
    """Raised when a filing XML can't be interpreted. Caller should
    log to etl_rejects rather than crash the pipeline."""


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_first(root: ET.Element, localname: str) -> ET.Element | None:
    """Depth-first search for the first descendant whose local tag matches."""
    if _localname(root.tag) == localname:
        return root
    for child in root:
        found = _find_first(child, localname)
        if found is not None:
            return found
    return None


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    text = (el.text or "").strip()
    return text or None


def _parse_sec_date(raw: str) -> date:
    """SEC cover pages use MM-DD-YYYY, info tables sometimes use ISO."""
    raw = raw.strip()
    if len(raw) == 10 and raw[2] == "-" and raw[5] == "-":
        month, day, year = raw.split("-")
        return date(int(year), int(month), int(day))
    return date.fromisoformat(raw)


def _normalize_put_call(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = raw.strip().upper()
    if upper in {"PUT", "CALL"}:
        return upper
    raise ParseError(f"unexpected putCall value: {raw!r}")


def _normalize_amendment_type(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = raw.strip().upper()
    if upper in {"RESTATEMENT", "NEW HOLDINGS"}:
        return upper
    raise ParseError(f"unexpected amendmentType value: {raw!r}")


def parse_cover(xml_path: Path) -> CoverInfo:
    root = ET.parse(xml_path).getroot()

    form_type_el = _find_first(root, "submissionType")
    period_el = _find_first(root, "periodOfReport")
    is_amend_el = _find_first(root, "isAmendment")
    amend_type_el = _find_first(root, "amendmentType")

    if form_type_el is None or _text(form_type_el) is None:
        raise ParseError(f"{xml_path}: no submissionType")
    if period_el is None or _text(period_el) is None:
        raise ParseError(f"{xml_path}: no periodOfReport")

    form_type = _text(form_type_el)
    assert form_type is not None
    period_text = _text(period_el)
    assert period_text is not None

    is_amendment = (_text(is_amend_el) or "").lower() == "true"
    amendment_type = _normalize_amendment_type(_text(amend_type_el))

    return CoverInfo(
        form_type=form_type,
        period_of_report=_parse_sec_date(period_text),
        is_amendment=is_amendment,
        amendment_type=amendment_type,
    )


def parse_information_table(
    xml_path: Path,
    filed_at: date,
    on_error: Callable[[ParseError], None] | None = None,
) -> Iterator[ParsedPosition]:
    """Parse a 13F info-table XML into positions. Value is normalized to
    whole dollars using the filing's `filed_at` date and the 2023-01-03
    unit-scaling rule.

    If `on_error` is provided, per-row ParseErrors are passed to it and
    the row is skipped; otherwise the error is raised (test-friendly)."""
    multiplier = Decimal(1000) if filed_at < VALUE_UNIT_DOLLARIZATION_CUTOFF else Decimal(1)

    root = ET.parse(xml_path).getroot()
    for info_table in root.iter():
        if _localname(info_table.tag) != "infoTable":
            continue
        try:
            yield _parse_info_table_row(info_table, multiplier)
        except ParseError as e:
            if on_error is None:
                raise
            on_error(e)


def _parse_info_table_row(el: ET.Element, multiplier: Decimal) -> ParsedPosition:
    fields: dict[str, str | None] = {}
    shrs_el: ET.Element | None = None
    for child in el:
        name = _localname(child.tag)
        if name == "shrsOrPrnAmt":
            shrs_el = child
        else:
            fields[name] = _text(child)

    cusip = fields.get("cusip")
    value_raw = fields.get("value")
    name_of_issuer = fields.get("nameOfIssuer")
    title_of_class = fields.get("titleOfClass")

    if not cusip:
        raise ParseError("infoTable row missing cusip")
    if value_raw is None:
        raise ParseError(f"infoTable row {cusip}: missing value")
    if not name_of_issuer:
        raise ParseError(f"infoTable row {cusip}: missing nameOfIssuer")
    if not title_of_class:
        raise ParseError(f"infoTable row {cusip}: missing titleOfClass")
    if shrs_el is None:
        raise ParseError(f"infoTable row {cusip}: missing shrsOrPrnAmt")

    ssh_prnamt = _text(_find_first(shrs_el, "sshPrnamt"))
    ssh_type = _text(_find_first(shrs_el, "sshPrnamtType"))
    if ssh_prnamt is None or ssh_type is None:
        raise ParseError(f"infoTable row {cusip}: missing shrsOrPrnAmt children")

    return ParsedPosition(
        name_of_issuer=name_of_issuer,
        title_of_class=title_of_class,
        cusip=cusip.strip(),
        figi=fields.get("figi"),
        value_usd=(Decimal(value_raw) * multiplier),
        shares=Decimal(ssh_prnamt),
        share_type=ssh_type.strip().upper(),
        put_call=_normalize_put_call(fields.get("putCall")),
        investment_discretion=fields.get("investmentDiscretion"),
    )


def aggregate_positions(
    rows: Iterable[ParsedPosition],
) -> Iterator[AggregatedPosition]:
    """Combine rows with the same (cusip, put_call) — the SPEC §4 rule
    for multiple managers reporting the same holding."""
    buckets: dict[tuple[str, str | None], AggregatedPosition] = {}
    for row in rows:
        key = (row.cusip, row.put_call)
        existing = buckets.get(key)
        if existing is None:
            buckets[key] = AggregatedPosition(
                name_of_issuer=row.name_of_issuer,
                title_of_class=row.title_of_class,
                cusip=row.cusip,
                figi=row.figi,
                put_call=row.put_call,
                shares=row.shares,
                share_type=row.share_type,
                value_usd=row.value_usd,
            )
        else:
            buckets[key] = AggregatedPosition(
                name_of_issuer=existing.name_of_issuer,
                title_of_class=existing.title_of_class,
                cusip=existing.cusip,
                figi=existing.figi or row.figi,
                put_call=existing.put_call,
                shares=existing.shares + row.shares,
                share_type=existing.share_type,
                value_usd=existing.value_usd + row.value_usd,
            )
    yield from buckets.values()
