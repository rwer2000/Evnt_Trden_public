"""One-off diagnostic: can we still DELETE from Supabase Storage even though
GET/POST are returning 402 Payment Required (free tier exceeded,
2026-09-28, confirmed live via query_logs across both Storage and
PostgREST)? Tries removing the single object in `congress-backups` --
the smallest, most trivially regenerable thing in either bucket (a weekly
`ops.db_backup` run recreates it on its own) -- and reports the exact
result. Run this before attempting any bulk cleanup of `congress-raw`;
direct SQL against `storage.objects` is not an option either way (blocked
by Supabase's own `storage.protect_delete()` trigger, confirmed live).

TEST_PATH is hardcoded rather than discovered via `.list()`: confirmed
live that LIST also 402s under this same quota block, so the one object's
name was instead read directly from `storage.objects` via SQL (unaffected,
same as every other direct Postgres access in this repo) and pasted in
here. If DELETE also turns out to be blocked, this script has done its job
either way -- there's nothing left downstream needing a dynamic listing.
"""

import logging

from congress_collector.storage import supabase_storage

logger = logging.getLogger(__name__)

BACKUP_BUCKET = "congress-backups"
TEST_PATH = "congress_20260921.sql.gz"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    logger.info("Attempting to delete %s/%s ...", BACKUP_BUCKET, TEST_PATH)
    try:
        result = supabase_storage.remove([TEST_PATH], bucket=BACKUP_BUCKET)
        logger.info("DELETE succeeded: %s", result)
    except Exception as exc:
        logger.error("DELETE failed: %s", exc)
        raise


if __name__ == "__main__":
    main()
