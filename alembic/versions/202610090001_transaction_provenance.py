"""transaction_provenance: how a transaction was read when not parsed

Revision ID: 202610090001
Revises: 202610080001
Create Date: 2026-10-09

Scanned PTRs without a text layer are transcribed with two independent
vision readings and imported by `ingest.transcribed_ptrs`. This table marks
those transactions (method 'transcribed') with the readings' combined
confidence, so analyses can include, exclude or weigh them. A separate
table rather than columns on `transactions`: the SQL Editor's role cannot
alter tables owned by `congress_app` (confirmed 2026-10-08), but can create
new ones and grant on them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "202610090001"
down_revision: str | None = "202610080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.create_table(
        "transaction_provenance",
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.transactions.transaction_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text()),
        sa.Column("review", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("source_file", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'congress_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.transaction_provenance TO congress_app; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN "
        f"GRANT SELECT ON {SCHEMA}.transaction_provenance TO service_role; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("transaction_provenance", schema=SCHEMA)
