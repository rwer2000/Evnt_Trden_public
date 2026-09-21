"""community_transactions: House/Senate Stock Watcher import (T21)

Revision ID: 202609210001
Revises: 202609200003
Create Date: 2026-09-21

Stores community-maintained congressional trading datasets (House Stock
Watcher, Senate Stock Watcher) as their own reference rows, kept separate
from `filings`/`transactions` -- those tables are for our own parsed
output, derived from our own archived raw source; mixing in an externally
parsed dataset with a different schema and different precision
guarantees would blur "source of truth" for every downstream consumer.

`matched_filing_id` links a community row to our own `filings` row when
one exists for the same underlying filing (House: direct DocID match via
their `filing_id` field; Senate: the report UUID embedded in their
`ptr_link` field) -- a community filing_id with no match is exactly the
survivorship-bias signal T21 calls for: something a community scraper
observed once that the official site no longer surfaces.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "202609210001"
down_revision: str | None = "202609200003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.create_table(
        "community_transactions",
        sa.Column(
            "community_transaction_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("extensions.gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("external_filing_id", sa.Text()),
        sa.Column(
            "matched_filing_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.filings.filing_id"),
        ),
        sa.Column("filer_name", sa.Text()),
        sa.Column("ticker", sa.Text()),
        sa.Column("asset_description", sa.Text()),
        sa.Column("asset_type", sa.Text()),
        sa.Column("tx_type", sa.Text()),
        sa.Column("owner", sa.Text()),
        sa.Column("tx_date", sa.Date()),
        sa.Column("disclosure_date", sa.Date()),
        sa.Column("amount_min", sa.Numeric()),
        sa.Column("amount_max", sa.Numeric()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source", "dedup_key", name="community_transactions_source_dedup_key"),
        schema=SCHEMA,
    )
    op.create_index(
        "community_transactions_external_filing_id_idx",
        "community_transactions",
        ["external_filing_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "community_transactions_matched_filing_id_idx",
        "community_transactions",
        ["matched_filing_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "community_transactions_matched_filing_id_idx",
        table_name="community_transactions",
        schema=SCHEMA,
    )
    op.drop_index(
        "community_transactions_external_filing_id_idx",
        table_name="community_transactions",
        schema=SCHEMA,
    )
    op.drop_table("community_transactions", schema=SCHEMA)
