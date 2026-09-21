"""Weekly database backup to Storage (T19).

Dumps the `congress` schema with `pg_dump` and uploads it, gzip-compressed,
to the `congress-backups` bucket -- a separate bucket from `congress-raw`
(raw filings), matching the project's existing isolation-by-bucket
convention (see README's "Database & storage" section). This is exactly
the `pg_dump --schema=congress` step that section already documents as the
way to migrate to a dedicated Supabase project later; running it weekly
just means a recent one always exists rather than being produced by hand
when the day comes.

`--no-owner --no-privileges` drops role-specific ALTER TABLE OWNER TO /
GRANT statements from the dump, since the exact role names on a future
restore target (a different Supabase project, someone's local Postgres)
aren't guaranteed to match this project's `congress_app` role -- the
schema and data restore cleanly either way; ownership/grants are trivial
to reapply by hand if needed.

`pg_dump` is a subprocess, not a Python library, so this can't be
meaningfully unit tested without a real Postgres server -- verified live
against production instead, same as every other DB-touching `ops`/`ingest`
module in this repo.
"""

import gzip
import os
import subprocess
from datetime import UTC, datetime

from congress_collector.notify.telegram import send_message
from congress_collector.storage.supabase_storage import upload

BACKUP_BUCKET = "congress-backups"
PG_DUMP_ARGS = ["--schema=congress", "--no-owner", "--no-privileges"]


def backup_object_key(today: datetime) -> str:
    return f"congress_{today:%Y%m%d}.sql.gz"


def create_backup(database_url: str) -> bytes:
    """Run `pg_dump` against `database_url` and return the gzip-compressed
    dump. Raises `subprocess.CalledProcessError` (with `pg_dump`'s stderr
    printed first, since the exception itself doesn't include it) if
    `pg_dump` fails."""
    result = subprocess.run(
        ["pg_dump", *PG_DUMP_ARGS, database_url],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.decode(errors="replace"))
        result.check_returncode()
    return gzip.compress(result.stdout)


def main() -> None:
    # pg_dump speaks libpq URLs directly (bare `postgresql://`), unlike
    # SQLAlchemy's engine which needs the `+psycopg` driver suffix -- read
    # DATABASE_URL from the environment as-is rather than going through
    # `db.session.get_engine()`.
    database_url = os.environ["DATABASE_URL"]
    dump = create_backup(database_url)
    object_key = backup_object_key(datetime.now(UTC))

    upload(object_key, dump, "application/gzip", bucket=BACKUP_BUCKET)

    size_kb = len(dump) / 1024
    send_message(f"Database backup complete: {object_key} ({size_kb:.0f} KB)", category="system")


if __name__ == "__main__":
    main()
