"""phase7 prices and etf_constituents

Revision ID: b3b10a94547a
Revises: 2d767686f413
Create Date: 2026-10-01 16:19:31.330038

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3b10a94547a"
down_revision: str | Sequence[str] | None = "2d767686f413"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etf_constituents",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("etf_security_id", sa.BigInteger(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("constituent_security_id", sa.BigInteger(), nullable=True),
        sa.Column("constituent_ticker", sa.String(), nullable=True),
        sa.Column("weight", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["constituent_security_id"], ["securities.id"]),
        sa.ForeignKeyConstraint(["etf_security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "etf_security_id",
            "as_of",
            "constituent_ticker",
            name="uq_etf_constituents_etf_asof_ticker",
        ),
    )
    op.create_index("ix_etf_constituents_etf", "etf_constituents", ["etf_security_id", "as_of"])
    op.create_table(
        "prices",
        sa.Column("security_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("security_id", "date"),
    )


def downgrade() -> None:
    op.drop_table("prices")
    op.drop_index("ix_etf_constituents_etf", table_name="etf_constituents")
    op.drop_table("etf_constituents")
