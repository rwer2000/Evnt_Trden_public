"""Daily check that R2 usage stays under the free-tier budget.

This is the alerting half of the guarantee described in `storage.quota`'s
docstring: reconciles the cached running total against R2 directly for
both buckets, and sends a Telegram alert once usage crosses
`quota.WARN_FRACTION` of the configured ceiling. The half that actually
blocks writes is `quota.ensure_budget()`, called from
house_pdfs.py/senate_ptrs.py/ops.db_backup before every upload -- this
script exists so a rising trend shows up well before that guard ever has
to reject anything.

Run daily by .github/workflows/check-storage-quota.yml.
"""

import logging

from congress_collector.notify.telegram import send_message
from congress_collector.storage import quota
from congress_collector.storage.r2_storage import BUCKET as RAW_BUCKET

logger = logging.getLogger(__name__)

BACKUP_BUCKET = "congress-backups"
BUCKETS = (RAW_BUCKET, BACKUP_BUCKET)


def check_bucket(bucket: str) -> tuple[int, float]:
    """Reconcile `bucket` against R2 and return (total_bytes, fraction of
    the configured ceiling used)."""
    total_bytes, _object_count = quota.reconcile(bucket)
    fraction = total_bytes / quota.ceiling_bytes()
    return total_bytes, fraction


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ceiling = quota.ceiling_bytes()

    for bucket in BUCKETS:
        total_bytes, fraction = check_bucket(bucket)
        logger.info(
            "%s: %.2f GB (%.0f%% of the %.0f GB budget)",
            bucket,
            total_bytes / 1024**3,
            fraction * 100,
            ceiling / 1024**3,
        )
        if fraction >= quota.WARN_FRACTION:
            send_message(
                f"R2 storage: {bucket} at {total_bytes / 1024**3:.2f} GB "
                f"({fraction * 100:.0f}% of the {ceiling / 1024**3:.0f} GB budget) -- "
                "new uploads to this bucket will start being rejected once it's full.",
                category="system",
            )


if __name__ == "__main__":
    main()
