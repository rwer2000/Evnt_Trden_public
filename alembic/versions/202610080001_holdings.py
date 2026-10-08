"""holdings: Schedule A of House annual Financial Disclosure reports

Revision ID: 202610080001
Revises: 202609280001
Create Date: 2026-10-08

One row per Schedule A line (asset, owner, value band, income) of a House
annual report (FilingType 'O'), parsed by `ingest.house_fds`. PTRs only
show trades; these show what a member already held, which is what the
strategy repository needs as a starting position per member. Confirmed on
80 electronic 2018 reports: 765 of 1,743 ticker holdings never appear in
that member's PTRs.

`congress-strategy` reads this table through PostgREST as `service_role`;
privileges granted on existing tables don't reach a new one, so SELECT is
granted here when that role exists (it does on Supabase, not in a bare
Postgres).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "202610080001"
down_revision: str | None = "202609280001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.create_table(
        "holdings",
        sa.Column(
            "holding_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("extensions.gen_random_uuid()"),
        ),
        sa.Column(
            "filing_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.filings.filing_id"), nullable=False
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("report_year", sa.Integer()),
        sa.Column("owner", sa.Text()),
        sa.Column("asset_description_raw", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text()),
        sa.Column("asset_type", sa.Text()),
        sa.Column("value_raw", sa.Text()),
        sa.Column("value_min", sa.Numeric()),
        sa.Column("value_max", sa.Numeric()),
        sa.Column("income_type", sa.Text()),
        sa.Column("income_raw", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("filing_id", "row_index"),
        schema=SCHEMA,
    )
    op.create_index("ix_holdings_ticker", "holdings", ["ticker"], schema=SCHEMA)
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN "
        f"GRANT SELECT ON {SCHEMA}.holdings TO service_role; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_index("ix_holdings_ticker", table_name="holdings", schema=SCHEMA)
    op.drop_table("holdings", schema=SCHEMA)
