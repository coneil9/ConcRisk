from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cik: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    filings: Mapped[list["Filing"]] = relationship(back_populates="fund")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (Index("ix_filings_fund_period", "fund_id", "period_of_report"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fund_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("funds.id", ondelete="CASCADE"), nullable=False
    )
    accession_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    form_type: Mapped[str] = mapped_column(String, nullable=False)
    period_of_report: Mapped[date] = mapped_column(Date, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    amendment_type: Mapped[str | None] = mapped_column(String, nullable=True)
    is_superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    raw_path: Mapped[str] = mapped_column(String, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    fund: Mapped[Fund] = relationship(back_populates="filings")
    positions: Mapped[list["Position"]] = relationship(back_populates="filing")


class Security(Base):
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cusip: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    figi: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    security_type: Mapped[str | None] = mapped_column(String, nullable=True)
    exch_code: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    sector_source: Mapped[str | None] = mapped_column(String, nullable=True)
    is_etf: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mapped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("filing_id", "security_id", "put_call", name="uq_positions_filing_sec_pc"),
        CheckConstraint(
            "put_call IS NULL OR put_call IN ('PUT','CALL')",
            name="ck_positions_put_call",
        ),
        Index("ix_positions_filing", "filing_id"),
        Index("ix_positions_security", "security_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("filings.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    put_call: Mapped[str | None] = mapped_column(String(4), nullable=True)
    shares: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    share_type: Mapped[str] = mapped_column(String(4), nullable=False)
    value_usd: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)

    filing: Mapped[Filing] = relationship(back_populates="positions")
    security: Mapped[Security] = relationship()


class EtlRun(Base):
    __tablename__ = "etl_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class EtlReject(Base):
    __tablename__ = "etl_rejects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("etl_runs.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    record: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
