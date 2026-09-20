"""core schema: politicians, filings, transactions, instruments, ticker_map,
scrape_runs, dq_issues

Revision ID: 202609190001
Revises:
Create Date: 2026-09-19

This revision was applied directly against the shared Supabase database
(project "Sportlogging", schema ``congress``) via the Supabase management
API before this file existed, because the schema is shared with the
congress-strategy repo and needed to exist before either repo's CI could
run migrations. If you are pointing a *fresh* database at this repo, run
``alembic upgrade head`` normally. Against the existing shared database,
run ``alembic stamp head`` instead so Alembic's bookkeeping matches
reality without re-running DDL that already exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "202609190001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"
GEN_UUID = sa.text("extensions.gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    op.create_table(
        "politicians",
        sa.Column("bioguide_id", sa.Text(), primary_key=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("party", sa.Text()),
        sa.Column("state", sa.Text()),
        sa.Column("district", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("chamber in ('house', 'senate')", name="politicians_chamber_check"),
        schema=SCHEMA,
    )

    op.create_table(
        "politician_terms",
        sa.Column("term_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "bioguide_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.politicians.bioguide_id"),
            nullable=False,
        ),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("state", sa.Text()),
        sa.Column("district", sa.Text()),
        sa.Column("party", sa.Text()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("chamber in ('house', 'senate')", name="politician_terms_chamber_check"),
        schema=SCHEMA,
    )
    op.create_index(
        "politician_terms_bioguide_idx", "politician_terms", ["bioguide_id"], schema=SCHEMA
    )

    op.create_table(
        "instruments",
        sa.Column("instrument_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column("primary_ticker", sa.Text()),
        sa.Column("cik", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("asset_class", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema=SCHEMA,
    )
    op.create_index(
        "instruments_primary_ticker_idx", "instruments", ["primary_ticker"], schema=SCHEMA
    )

    op.create_table(
        "ticker_map",
        sa.Column("ticker_map_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "instrument_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.instruments.instrument_id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source", sa.Text(), nullable=False, server_default="sec"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema=SCHEMA,
    )
    op.create_index("ticker_map_ticker_idx", "ticker_map", ["ticker"], schema=SCHEMA)
    op.create_index("ticker_map_instrument_idx", "ticker_map", ["instrument_id"], schema=SCHEMA)

    op.create_table(
        "filings",
        sa.Column("filing_id", sa.Text(), primary_key=True),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("filer_name", sa.Text(), nullable=False),
        sa.Column("bioguide_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.politicians.bioguide_id")),
        sa.Column("filing_type", sa.Text(), nullable=False),
        sa.Column("filed_date", sa.Date()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_precision_s", sa.Integer(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("parse_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("source", sa.Text(), nullable=False, server_default="official"),
        sa.Column("raw_object_key", sa.Text()),
        sa.Column("raw_sha256", sa.Text()),
        sa.Column("supersedes_filing_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.filings.filing_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("chamber in ('house', 'senate')", name="filings_chamber_check"),
        sa.CheckConstraint(
            "format in ('electronic', 'paper', 'scanned')", name="filings_format_check"
        ),
        sa.CheckConstraint(
            "parse_status in ('pending', 'parsed', 'paper_deferred', 'failed')",
            name="filings_parse_status_check",
        ),
        schema=SCHEMA,
    )
    op.create_index("filings_bioguide_idx", "filings", ["bioguide_id"], schema=SCHEMA)
    op.create_index("filings_first_seen_idx", "filings", ["first_seen_at"], schema=SCHEMA)
    op.create_index("filings_chamber_idx", "filings", ["chamber"], schema=SCHEMA)

    op.create_table(
        "transactions",
        sa.Column("transaction_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column(
            "filing_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.filings.filing_id"), nullable=False
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("owner", sa.Text()),
        sa.Column("asset_description_raw", sa.Text(), nullable=False),
        sa.Column("asset_type", sa.Text()),
        sa.Column("ticker", sa.Text()),
        sa.Column("cik", sa.Text()),
        sa.Column(
            "instrument_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.instruments.instrument_id"),
        ),
        sa.Column("option_type", sa.Text()),
        sa.Column("strike", sa.Numeric()),
        sa.Column("expiry", sa.Date()),
        sa.Column("underlying_ticker", sa.Text()),
        sa.Column("tx_type", sa.Text(), nullable=False),
        sa.Column("tx_date", sa.Date()),
        sa.Column("notification_date", sa.Date()),
        sa.Column("amount_min", sa.Numeric()),
        sa.Column("amount_max", sa.Numeric()),
        sa.Column("filing_delay_days", sa.Integer()),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("filing_id", "row_index"),
        sa.CheckConstraint(
            "owner in ('self', 'spouse', 'joint', 'child')", name="transactions_owner_check"
        ),
        sa.CheckConstraint("option_type in ('call', 'put')", name="transactions_option_type_check"),
        sa.CheckConstraint(
            "tx_type in ('purchase', 'sale_full', 'sale_partial', 'exchange')",
            name="transactions_tx_type_check",
        ),
        schema=SCHEMA,
    )
    op.create_index("transactions_filing_idx", "transactions", ["filing_id"], schema=SCHEMA)
    op.create_index("transactions_ticker_idx", "transactions", ["ticker"], schema=SCHEMA)
    op.create_index("transactions_tx_date_idx", "transactions", ["tx_date"], schema=SCHEMA)
    op.create_index("transactions_instrument_idx", "transactions", ["instrument_id"], schema=SCHEMA)

    op.create_table(
        "scrape_runs",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("new_filings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint("chamber in ('house', 'senate')", name="scrape_runs_chamber_check"),
        sa.CheckConstraint(
            "status in ('running', 'success', 'failed')", name="scrape_runs_status_check"
        ),
        schema=SCHEMA,
    )
    op.create_index("scrape_runs_started_idx", "scrape_runs", ["started_at"], schema=SCHEMA)

    op.create_table(
        "dq_issues",
        sa.Column("issue_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column("filing_id", sa.Text(), sa.ForeignKey(f"{SCHEMA}.filings.filing_id")),
        sa.Column(
            "transaction_id",
            UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.transactions.transaction_id"),
        ),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.create_index("dq_issues_filing_idx", "dq_issues", ["filing_id"], schema=SCHEMA)
    op.create_index("dq_issues_type_idx", "dq_issues", ["issue_type"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("dq_issues", schema=SCHEMA)
    op.drop_table("scrape_runs", schema=SCHEMA)
    op.drop_table("transactions", schema=SCHEMA)
    op.drop_table("filings", schema=SCHEMA)
    op.drop_table("ticker_map", schema=SCHEMA)
    op.drop_table("instruments", schema=SCHEMA)
    op.drop_table("politician_terms", schema=SCHEMA)
    op.drop_table("politicians", schema=SCHEMA)
