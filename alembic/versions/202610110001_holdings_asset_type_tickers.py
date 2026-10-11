"""holdings_asset_type_tickers: clear tickers that are asset-type codes

Revision ID: 202610110001
Revises: 202610090001
Create Date: 2026-10-11

Data-only. Some Schedule A lines carry the filer's asset-type code in the
ticker's parentheses ("Berkshire Hathaway CL B New (MF) [BA]"), which the
parser read as ticker MF. `parsers.house_fd._ticker_or_none` now drops such
a ticker when the row has a bracketed type other than a traded-equity one
(ST, OL, AB); this applies the same rule to rows already stored. Counted on
2026-10-11 via PostgREST: 117 of the 505 holdings whose ticker spells a code
(27 filings); the other 388 are real tickers (Boeing "(BA) [ST]",
AllianceBernstein "(AB) [OL]") or untyped pre-2019 rows, and stay.

Equivalent to re-parsing those filings, without touching anything else:
re-parsing every description with the new parser gives exactly these 117
changes. Can also be run by hand in the SQL Editor (the UPDATE below).

downgrade() restores the old tickers from the descriptions with the
parser's former "(TICKER) [TYPE]" rule.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202610110001"
down_revision: str | None = "202610090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"

# Must match parsers.house_fd.ASSET_TYPE_CODES / _EQUITY_TYPES at the time
# of writing (a migration doesn't import app code that may change later).
_CODES = (
    "'AB','BA','CO','CS','DB','DO','EF','EQ','ET','ETF','FA','FN','GS','HE',"
    "'IH','IP','MF','OI','OL','OP','OT','PE','PS','RE','RP','SA','ST','WU'"
)
_EQUITY_TYPES = "'ST','OL','AB'"
_TICKER_TYPE_RE = r"\(([A-Za-z0-9.\-/]{1,15})\)\s*\[([A-Za-z]{1,4})\]\s*$"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.holdings SET ticker = NULL "
            f"WHERE ticker IN ({_CODES}) "
            f"AND asset_type IS NOT NULL AND asset_type NOT IN ({_EQUITY_TYPES})"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.holdings "
            f"SET ticker = upper((regexp_match(asset_description_raw, :pattern))[1]) "
            f"WHERE ticker IS NULL "
            f"AND asset_type IS NOT NULL AND asset_type NOT IN ({_EQUITY_TYPES}) "
            f"AND upper((regexp_match(asset_description_raw, :pattern))[1]) IN ({_CODES})"
        ).bindparams(pattern=_TICKER_TYPE_RE)
    )
