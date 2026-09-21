"""instruments: sic + sic_description + sic_synced_at (T24)

Revision ID: 202609210003
Revises: 202609210002
Create Date: 2026-09-21

Sector proxy for T25's planned committee<->sector overlap flag: SEC EDGAR's
submissions API returns a SIC (Standard Industrial Classification) code
and description per CIK, and `instruments.cik` is already populated by
T14's ticker linking.

`sic_synced_at` (nullable, set on every sync attempt regardless of
outcome) distinguishes "never tried yet" from "tried, SEC has no SIC for
this entity" -- a handful of filers (foreign private issuers, trusts,
some ETFs) genuinely have none, and without this column the sync would
retry those every run forever.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202609210003"
down_revision: str | None = "202609210002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.add_column("instruments", sa.Column("sic", sa.Text()), schema=SCHEMA)
    op.add_column("instruments", sa.Column("sic_description", sa.Text()), schema=SCHEMA)
    op.add_column(
        "instruments",
        sa.Column("sic_synced_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("instruments", "sic_synced_at", schema=SCHEMA)
    op.drop_column("instruments", "sic_description", schema=SCHEMA)
    op.drop_column("instruments", "sic", schema=SCHEMA)
