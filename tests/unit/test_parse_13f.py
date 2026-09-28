from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from concrisk.etl.parse_13f import (
    ParseError,
    aggregate_positions,
    parse_cover,
    parse_information_table,
)

REF = Path("reference/13f")


def test_cover_pre_2023() -> None:
    cover = parse_cover(REF / "berkshire-2022Q3/primary_doc.xml")
    assert cover.form_type == "13F-HR"
    assert cover.period_of_report == date(2022, 9, 30)
    assert cover.is_amendment is False
    assert cover.amendment_type is None


def test_cover_post_2023() -> None:
    cover = parse_cover(REF / "berkshire-2025Q1/primary_doc.xml")
    assert cover.form_type == "13F-HR"
    assert cover.period_of_report == date(2025, 3, 31)


def test_parses_pre_2023_thousands() -> None:
    # HAND-COMPUTED: filed 2022-11-14 is BEFORE the 2023-01-03 cutoff,
    # so raw value is in thousands and must be multiplied by 1000.
    # Apple row raw value = 123661679 (thousands) → $123,661,679,000.
    # Total across 49 aggregated positions = $296,096,640,000
    # (matches the ~$296B Berkshire portfolio publicly reported for Q3 2022).
    rows = list(parse_information_table(REF / "berkshire-2022Q3/infotable.xml", date(2022, 11, 14)))
    assert len(rows) == 179
    agg = {p.cusip: p for p in aggregate_positions(rows)}
    assert len(agg) == 49

    apple = agg["037833100"]
    assert apple.name_of_issuer == "APPLE INC"
    assert apple.shares == Decimal("894802319")
    assert apple.value_usd == Decimal("123661679000")

    total = sum((p.value_usd for p in agg.values()), Decimal(0))
    assert total == Decimal("296096640000")


def test_parses_post_2023_dollars() -> None:
    # HAND-COMPUTED: filed 2025-05-15 is AFTER the 2023-01-03 cutoff,
    # so raw value is already in whole dollars.
    # Apple row: 300,000,000 shares reported at $66,639,000,000
    # (~$222.13/share, matches Apple's March 31, 2025 close).
    # Total across 36 aggregated positions = $258,701,144,516.
    rows = list(parse_information_table(REF / "berkshire-2025Q1/infotable.xml", date(2025, 5, 15)))
    assert len(rows) == 110
    agg = {p.cusip: p for p in aggregate_positions(rows)}
    assert len(agg) == 36

    apple = agg["037833100"]
    assert apple.name_of_issuer == "APPLE INC"
    assert apple.shares == Decimal("300000000")
    assert apple.value_usd == Decimal("66639000000")

    total = sum((p.value_usd for p in agg.values()), Decimal(0))
    assert total == Decimal("258701144516")


_MINIMAL_XML = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000000000</cusip>
    <value>1000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>100</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


@pytest.mark.parametrize(
    ("filed_at", "expected"),
    [
        (date(2022, 12, 31), Decimal("1000000")),  # thousands regime
        (date(2023, 1, 2), Decimal("1000000")),  # last thousands day
        (date(2023, 1, 3), Decimal("1000")),  # first dollars day (cutoff inclusive)
        (date(2023, 1, 4), Decimal("1000")),  # dollars regime
        (date(2025, 5, 15), Decimal("1000")),  # dollars regime
    ],
)
def test_value_unit_boundary(tmp_path: Path, filed_at: date, expected: Decimal) -> None:
    p = tmp_path / "info.xml"
    p.write_text(_MINIMAL_XML)
    rows = list(parse_information_table(p, filed_at))
    assert rows[0].value_usd == expected


_DUPLICATE_XML = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000000000</cusip>
    <value>1000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000000000</cusip>
    <value>500</value>
    <shrsOrPrnAmt>
      <sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
</informationTable>"""


def test_aggregates_duplicate_cusip_rows(tmp_path: Path) -> None:
    # HAND-COMPUTED: two rows for CUSIP 000000000, same put_call (None).
    # Aggregation sums to shares=150, value_usd=1500 (dollars regime).
    p = tmp_path / "info.xml"
    p.write_text(_DUPLICATE_XML)
    rows = list(parse_information_table(p, date(2025, 5, 15)))
    assert len(rows) == 2

    agg = list(aggregate_positions(rows))
    assert len(agg) == 1
    assert agg[0].cusip == "000000000"
    assert agg[0].shares == Decimal("150")
    assert agg[0].value_usd == Decimal("1500")


_OPTIONS_XML = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>000000000</cusip><value>1000</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>CALL</titleOfClass>
    <cusip>000000000</cusip><value>200</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Call</putCall>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>PUT</titleOfClass>
    <cusip>000000000</cusip><value>50</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Put</putCall>
  </infoTable>
</informationTable>"""


def test_options_put_call_split(tmp_path: Path) -> None:
    p = tmp_path / "info.xml"
    p.write_text(_OPTIONS_XML)
    rows = list(parse_information_table(p, date(2025, 5, 15)))

    agg = {a.put_call: a for a in aggregate_positions(rows)}
    assert set(agg.keys()) == {None, "CALL", "PUT"}
    assert agg[None].value_usd == Decimal("1000")
    assert agg["CALL"].value_usd == Decimal("200")
    assert agg["PUT"].value_usd == Decimal("50")


_MISSING_CUSIP_XML = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <value>1000</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_row_error_raised_by_default(tmp_path: Path) -> None:
    p = tmp_path / "info.xml"
    p.write_text(_MISSING_CUSIP_XML)
    with pytest.raises(ParseError):
        list(parse_information_table(p, date(2025, 5, 15)))


def test_row_error_captured_by_on_error(tmp_path: Path) -> None:
    p = tmp_path / "info.xml"
    p.write_text(_MISSING_CUSIP_XML)
    errors: list[ParseError] = []

    rows = list(parse_information_table(p, date(2025, 5, 15), on_error=errors.append))

    assert rows == []
    assert len(errors) == 1
    assert "cusip" in str(errors[0]).lower()
