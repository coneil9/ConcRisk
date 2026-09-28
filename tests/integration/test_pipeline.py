from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import EtlRun, Filing, Fund, Position
from concrisk.etl.openfigi import SecurityMapping
from concrisk.etl.pipeline import run
from concrisk.etl.sec_client import FilingArtifacts, SubmissionRow

pytestmark = pytest.mark.integration

BERK_CIK = "0001067983"


class FakeSecClient:
    def __init__(
        self,
        filings: dict[str, list[SubmissionRow]],
        artifacts: dict[str, FilingArtifacts],
    ) -> None:
        self._filings = filings
        self._artifacts = artifacts
        self.fetch_calls = 0

    def list_filings(self, cik: str) -> list[SubmissionRow]:
        return self._filings.get(cik.zfill(10), [])

    def fetch_filing(self, cik: str, accession_no: str) -> FilingArtifacts:
        self.fetch_calls += 1
        return self._artifacts[accession_no]

    def close(self) -> None:
        pass


class FakeOpenFigiClient:
    batch_size = 100

    def __init__(self, mappings: dict[str, SecurityMapping | None] | None = None) -> None:
        self._mappings = mappings or {}
        self.call_count = 0

    def resolve_cusips_batch(self, cusips: list[str]) -> dict[str, SecurityMapping | None]:
        self.call_count += 1
        # Default: return None for anything not explicitly mapped.
        return {c: self._mappings.get(c) for c in cusips}

    def close(self) -> None:
        pass


@pytest.fixture
def berkshire_2025_artifacts() -> FilingArtifacts:
    ref = Path("reference/13f/berkshire-2025Q1")
    return FilingArtifacts(
        cover_path=ref / "primary_doc.xml",
        info_table_path=ref / "infotable.xml",
    )


@pytest.fixture
def berkshire_2025_submission() -> SubmissionRow:
    return SubmissionRow(
        accession_no="0000950123-25-005701",
        form_type="13F-HR",
        filed_at=date(2025, 5, 15),
        period_of_report=date(2025, 3, 31),
        primary_document="primary_doc.xml",
    )


def test_pipeline_loads_filing_end_to_end(
    db_session: Session,
    berkshire_2025_artifacts: FilingArtifacts,
    berkshire_2025_submission: SubmissionRow,
) -> None:
    sec = FakeSecClient(
        filings={BERK_CIK: [berkshire_2025_submission]},
        artifacts={berkshire_2025_submission.accession_no: berkshire_2025_artifacts},
    )
    figi = FakeOpenFigiClient()

    stats = run(
        quarters=20,  # far enough back to include 2025-03-31
        funds_filter={BERK_CIK},
        session=db_session,
        sec=sec,  # type: ignore[arg-type]
        figi=figi,  # type: ignore[arg-type]
    )

    assert stats == {
        "funds": 1,
        "filings_loaded": 1,
        "filings_skipped": 0,
        "positions": 36,
        "rejects": 0,
    }
    assert (
        db_session.execute(select(Fund).where(Fund.cik == BERK_CIK)).scalar_one().name
        == "Berkshire Hathaway"
    )
    filing = db_session.execute(
        select(Filing).where(Filing.accession_no == berkshire_2025_submission.accession_no)
    ).scalar_one()
    assert filing.period_of_report == date(2025, 3, 31)
    assert filing.form_type == "13F-HR"
    assert filing.amendment_type is None
    assert filing.is_superseded is False

    positions = (
        db_session.execute(select(Position).where(Position.filing_id == filing.id)).scalars().all()
    )
    assert len(positions) == 36

    run_row = db_session.execute(select(EtlRun)).scalars().first()
    assert run_row is not None
    assert run_row.status == "ok"
    assert run_row.stats["positions"] == 36


def test_pipeline_skips_already_loaded_filing_by_default(
    db_session: Session,
    berkshire_2025_artifacts: FilingArtifacts,
    berkshire_2025_submission: SubmissionRow,
) -> None:
    sec = FakeSecClient(
        filings={BERK_CIK: [berkshire_2025_submission]},
        artifacts={berkshire_2025_submission.accession_no: berkshire_2025_artifacts},
    )
    figi = FakeOpenFigiClient()

    run(
        quarters=20,
        funds_filter={BERK_CIK},
        session=db_session,
        sec=sec,  # type: ignore[arg-type]
        figi=figi,  # type: ignore[arg-type]
    )
    initial_fetches = sec.fetch_calls

    stats2 = run(
        quarters=20,
        funds_filter={BERK_CIK},
        session=db_session,
        sec=sec,  # type: ignore[arg-type]
        figi=figi,  # type: ignore[arg-type]
    )

    assert stats2["filings_loaded"] == 0
    assert stats2["filings_skipped"] == 1
    assert sec.fetch_calls == initial_fetches  # no re-fetch

    filings = db_session.execute(select(Filing)).scalars().all()
    assert len(filings) == 1  # still one filing


_AMENDMENT_COVER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData>
    <submissionType>13F-HR/A</submissionType>
    <filerInfo>
      <periodOfReport>03-31-2025</periodOfReport>
    </filerInfo>
  </headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2025</reportCalendarOrQuarter>
      <isAmendment>true</isAmendment>
      <amendmentInfo>
        <amendmentNo>1</amendmentNo>
        <amendmentType>RESTATEMENT</amendmentType>
        <dateOfOriginalReport>05-15-2025</dateOfOriginalReport>
      </amendmentInfo>
    </coverPage>
  </formData>
</edgarSubmission>"""

_AMENDMENT_INFO_XML = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>1000</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_pipeline_restatement_marks_prior_filings_superseded(
    db_session: Session,
    tmp_path: Path,
    berkshire_2025_artifacts: FilingArtifacts,
    berkshire_2025_submission: SubmissionRow,
) -> None:
    # First load the original 13F-HR.
    original_sec = FakeSecClient(
        filings={BERK_CIK: [berkshire_2025_submission]},
        artifacts={berkshire_2025_submission.accession_no: berkshire_2025_artifacts},
    )
    run(
        quarters=20,
        funds_filter={BERK_CIK},
        session=db_session,
        sec=original_sec,  # type: ignore[arg-type]
        figi=FakeOpenFigiClient(),  # type: ignore[arg-type]
    )

    # Now feed a RESTATEMENT amendment for the same (fund, period).
    cover_path = tmp_path / "amend_cover.xml"
    info_path = tmp_path / "amend_info.xml"
    cover_path.write_text(_AMENDMENT_COVER_XML)
    info_path.write_text(_AMENDMENT_INFO_XML)

    amendment = SubmissionRow(
        accession_no="0000950123-25-008361",
        form_type="13F-HR/A",
        filed_at=date(2025, 8, 14),
        period_of_report=date(2025, 3, 31),
        primary_document="primary_doc.xml",
    )
    amend_sec = FakeSecClient(
        filings={BERK_CIK: [amendment]},
        artifacts={
            amendment.accession_no: FilingArtifacts(
                cover_path=cover_path, info_table_path=info_path
            )
        },
    )
    run(
        quarters=20,
        funds_filter={BERK_CIK},
        session=db_session,
        sec=amend_sec,  # type: ignore[arg-type]
        figi=FakeOpenFigiClient(),  # type: ignore[arg-type]
    )

    filings = db_session.execute(select(Filing).order_by(Filing.filed_at)).scalars().all()
    by_accession = {f.accession_no: f for f in filings}

    original = by_accession[berkshire_2025_submission.accession_no]
    amend = by_accession[amendment.accession_no]

    assert original.is_superseded is True
    assert amend.is_superseded is False
    assert amend.amendment_type == "RESTATEMENT"
