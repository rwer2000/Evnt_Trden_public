"""storage_usage: cached running total per R2 bucket

Revision ID: 202609280001
Revises: 202609210003
Create Date: 2026-09-28

Backs the free-tier budget guard in `storage.quota`: Cloudflare's own R2
dashboard only offers usage *notifications*, not a hard stop on requests,
so guaranteeing the archive never crosses the 10 GiB free tier means
checking a running total before every upload ourselves. A row per bucket
here is that running total -- cheap to read on the hot path, since the
alternative (listing the bucket from R2 on every upload) would mean a
paginated walk over 25k+ objects each time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202609280001"
down_revision: str | None = "202609210003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "congress"


def upgrade() -> None:
    op.create_table(
        "storage_usage",
        sa.Column("bucket", sa.Text(), primary_key=True),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("object_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("storage_usage", schema=SCHEMA)
