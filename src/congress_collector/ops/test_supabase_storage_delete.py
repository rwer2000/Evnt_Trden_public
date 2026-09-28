"""One-off diagnostic: can we still DELETE from Supabase Storage even though
GET/POST are returning 402 Payment Required (free tier exceeded,
2026-09-28, confirmed live via query_logs across both Storage and
PostgREST)? Tries removing the single object in `congress-backups` --
the smallest, most trivially regenerable thing in either bucket (a weekly
`ops.db_backup` run recreates it on its own) -- and reports the exact
result. Run this before attempting any bulk cleanup of `congress-raw`;
direct SQL against `storage.objects` is not an option either way (blocked
by Supabase's own `storage.protect_delete()` trigger, confirmed live).
"""

import logging

from congress_collector.storage import supabase_storage

logger = logging.getLogger(__name__)

BACKUP_BUCKET = "congress-backups"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = supabase_storage.get_client()
    entries = client.storage.from_(BACKUP_BUCKET).list()
    if not entries:
        logger.info("%s: no objects found to test against", BACKUP_BUCKET)
        return

    test_path = entries[0]["name"]
    logger.info("Attempting to delete %s/%s ...", BACKUP_BUCKET, test_path)
    try:
        result = supabase_storage.remove([test_path], bucket=BACKUP_BUCKET)
        logger.info("DELETE succeeded: %s", result)
    except Exception as exc:
        logger.error("DELETE failed: %s", exc)
        raise


if __name__ == "__main__":
    main()
