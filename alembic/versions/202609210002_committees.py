"""committees + committee_memberships: congress-legislators committee data (T23)

Revision ID: 202609210002
Revises: 202609210001
Create Date: 2026-09-21

Top-level committees only (subcommittees are dropped at ingest time --
see sources/committees.py's module docstring): this collector only needs
"which committees is this person on" for the Telegram notification (T22)
and T25's planned sector-overlap flag, and subcommittee membership
multiplies the row count several-fold without adding a meaningfully
different jurisdiction signal.

`committee_memberships` is fully replaced on every sync (same pattern as
T13's `politician_terms`): the YAML file is the single source of truth
and nothing else writes to this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "202609210002"
down_revision: str | None = "202609210001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "committees",
        sa.Column("thomas_id", sa.Text(), primary_key=True),
        sa.Column("chamber", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema=SCHEMA,
    )

    op.create_table(
        "committee_memberships",
        sa.Column(
            "membership_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("extensions.gen_random_uuid()"),
        ),
        sa.Column(
            "thomas_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.committees.thomas_id"),
            nullable=False,
        ),
        sa.Column(
            "bioguide_id",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.politicians.bioguide_id"),
            nullable=False,
        ),
        sa.Column("party", sa.Text()),
        sa.Column("rank", sa.Integer()),
        sa.Column("title", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        schema=SCHEMA,
    )
    op.create_index(
        "committee_memberships_bioguide_id_idx",
        "committee_memberships",
        ["bioguide_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "committee_memberships_thomas_id_idx",
        "committee_memberships",
        ["thomas_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "committee_memberships_thomas_id_idx", table_name="committee_memberships", schema=SCHEMA
    )
    op.drop_index(
        "committee_memberships_bioguide_id_idx", table_name="committee_memberships", schema=SCHEMA
    )
    op.drop_table("committee_memberships", schema=SCHEMA)
    op.drop_table("committees", schema=SCHEMA)
