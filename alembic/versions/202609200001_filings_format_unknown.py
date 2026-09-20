"""filings.format: allow 'unknown' (recorded before T7/T8 classify it)

Revision ID: 202609200001
Revises: 202609190001
Create Date: 2026-09-20

Applied directly against the shared Supabase database first (see the
previous revision's docstring for why); run `alembic stamp head` against
the real database rather than `upgrade head` if it's already there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202609200001"
down_revision: str | None = "202609190001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"
OLD_VALUES = ("electronic", "paper", "scanned")
NEW_VALUES = (*OLD_VALUES, "unknown")


def upgrade() -> None:
    op.drop_constraint("filings_format_check", "filings", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "filings_format_check",
        "filings",
        sa.column("format").in_(NEW_VALUES),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("filings_format_check", "filings", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "filings_format_check",
        "filings",
        sa.column("format").in_(OLD_VALUES),
        schema=SCHEMA,
    )
