"""future_filed_dates: clear House filing dates that lie in the future

Revision ID: 202610190001
Revises: 202610110001
Create Date: 2026-10-19

Data-only. The House Clerk's index has typos in FilingDate ("6/14/3013" in
the 2013 index, "5/15/2031" in 2021); the T20 backfill stored them and
derived first_seen_at from them, so six filings (house:8212287-8212289,
house:9102567-9102569, all type O, counted 2026-10-19 via PostgREST) look
first seen in 3013 and 2031. `sources.house.plausible_filing_date` now
drops such dates at parse time; this applies the same to rows already
stored: filed_date becomes NULL and first_seen_at the row's created_at
(when the backfill inserted it, the honest upper bound), flagged with the
unknown-date precision sentinel the backfill uses for undated entries.

The WHERE clause only matches dates after the row was created, so it is a
no-op on correct data and safe to run twice. Can also be run by hand in the
SQL Editor (the UPDATE below).

downgrade() is a no-op: the typo'd dates were wrong, and the raw index
still has them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202610190001"
down_revision: str | None = "202610110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"
# Must match ingest.house.BACKFILL_UNKNOWN_DATE_PRECISION_S at the time of
# writing (a migration doesn't import app code that may change later).
_UNKNOWN_PRECISION_S = 315_360_000


def upgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.filings "
            f"SET filed_date = NULL, first_seen_at = created_at, "
            f"first_seen_precision_s = {_UNKNOWN_PRECISION_S} "
            f"WHERE filed_date > (created_at AT TIME ZONE 'UTC')::date + 1"
        )
    )


def downgrade() -> None:
    pass
