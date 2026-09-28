"""phase1 baseline

Revision ID: 2d767686f413
Revises:
Create Date: 2026-09-28 15:18:06.492494

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2d767686f413"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etl_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "funds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("cik", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cik"),
    )
    op.create_table(
        "securities",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("cusip", sa.String(), nullable=False),
        sa.Column("figi", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("security_type", sa.String(), nullable=True),
        sa.Column("exch_code", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("sector_source", sa.String(), nullable=True),
        sa.Column("is_etf", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mapped_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cusip"),
    )
    op.create_table(
        "etl_rejects",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["etl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "filings",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("fund_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_no", sa.String(), nullable=False),
        sa.Column("form_type", sa.String(), nullable=False),
        sa.Column("period_of_report", sa.Date(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=False),
        sa.Column("amendment_type", sa.String(), nullable=True),
        sa.Column("is_superseded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("raw_path", sa.String(), nullable=False),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["fund_id"], ["funds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_no"),
    )
    op.create_index("ix_filings_fund_period", "filings", ["fund_id", "period_of_report"])
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("security_id", sa.BigInteger(), nullable=False),
        sa.Column("put_call", sa.String(length=4), nullable=True),
        sa.Column("shares", sa.Numeric(), nullable=False),
        sa.Column("share_type", sa.String(length=4), nullable=False),
        sa.Column("value_usd", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.CheckConstraint(
            "put_call IS NULL OR put_call IN ('PUT','CALL')",
            name="ck_positions_put_call",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "filing_id",
            "security_id",
            "put_call",
            name="uq_positions_filing_sec_pc",
        ),
    )
    op.create_index("ix_positions_filing", "positions", ["filing_id"])
    op.create_index("ix_positions_security", "positions", ["security_id"])


def downgrade() -> None:
    op.drop_index("ix_positions_security", table_name="positions")
    op.drop_index("ix_positions_filing", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_filings_fund_period", table_name="filings")
    op.drop_table("filings")
    op.drop_table("etl_rejects")
    op.drop_table("securities")
    op.drop_table("funds")
    op.drop_table("etl_runs")
