"""politician_overrides: manual filer_name -> bioguide_id overrides (T13)

Revision ID: 202609200002
Revises: 202609200001
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "202609200002"
down_revision: str | None = "202609200001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"
GEN_UUID = sa.text("extensions.gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "politician_overrides",
        sa.Column("override_id", UUID(as_uuid=True), primary_key=True, server_default=GEN_UUID),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("filer_name", sa.Text(), nullable=False),
        sa.Column(
            "bioguide_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.politicians.bioguide_id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("chamber", "filer_name", name="politician_overrides_chamber_name_uq"),
        sa.CheckConstraint(
            "chamber in ('house', 'senate')", name="politician_overrides_chamber_check"
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("politician_overrides", schema=SCHEMA)
