"""transactions.source_transaction_id: House PTR's per-row numeric ID (T16)

Revision ID: 202609200003
Revises: 202609200002
Create Date: 2026-09-20

The House PTR form's leftmost "ID" column is a persistent per-transaction
identifier that stays the same across an original filing and any later
amendment that corrects it -- confirmed live against a real filing with a
"Filing Status: Amended" row. Senate has no equivalent, so this column
stays NULL there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202609200003"
down_revision: str | None = "202609200002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.add_column("transactions", sa.Column("source_transaction_id", sa.Text()), schema=SCHEMA)
    op.create_index(
        "transactions_source_transaction_id_idx",
        "transactions",
        ["source_transaction_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "transactions_source_transaction_id_idx", table_name="transactions", schema=SCHEMA
    )
    op.drop_column("transactions", "source_transaction_id", schema=SCHEMA)
