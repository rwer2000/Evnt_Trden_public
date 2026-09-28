"""Guards against R2 usage exceeding the free-tier budget.

Cloudflare's own R2 dashboard only offers usage *notifications* -- an
email/webhook once you cross a threshold you configure -- not a hard stop
on requests. There's no dashboard toggle that guarantees "never go over
the free 10 GiB", so that guarantee is enforced here instead, against a
running total kept in Postgres (`congress.storage_usage`):

- `ensure_budget()` is called before every archive upload
  (house_pdfs.py/senate_ptrs.py/ops.db_backup) and raises rather than let
  a write through that would cross the ceiling.
- `record_bytes()` keeps that running total current after each successful
  upload, without an R2 API round-trip on the hot path.
- `reconcile()` recomputes the true total directly from R2 (a paginated
  ListObjectsV2 walk) and corrects any drift -- run daily by
  ops.check_storage_quota, and once at the end of the initial
  ops.migrate_raw_archive_to_r2 run to seed the counter correctly.
"""

import os

from sqlalchemy.dialects.postgresql import insert

from congress_collector.db.models import StorageUsage
from congress_collector.db.session import session_scope
from congress_collector.storage import r2_storage

DEFAULT_CEILING_BYTES = 9 * 1024**3  # 9 GiB -- headroom under R2's 10 GiB free tier
WARN_FRACTION = 0.8


class StorageBudgetExceededError(Exception):
    pass


def ceiling_bytes() -> int:
    return int(os.environ.get("R2_STORAGE_CEILING_BYTES", DEFAULT_CEILING_BYTES))


def would_exceed(current_bytes: int, additional_bytes: int, ceiling: int) -> bool:
    return current_bytes + additional_bytes > ceiling


def current_usage_bytes(bucket: str) -> int:
    with session_scope() as session:
        usage = session.get(StorageUsage, bucket)
        return usage.total_bytes if usage is not None else 0


def ensure_budget(bucket: str, additional_bytes: int) -> None:
    """Raise StorageBudgetExceededError if uploading `additional_bytes` more
    to `bucket` would push its running total past the configured ceiling."""
    ceiling = ceiling_bytes()
    current = current_usage_bytes(bucket)
    if would_exceed(current, additional_bytes, ceiling):
        raise StorageBudgetExceededError(
            f"{bucket}: {current + additional_bytes} bytes would exceed the {ceiling}-byte budget"
        )


def record_bytes(bucket: str, additional_bytes: int) -> None:
    """Add `additional_bytes` to `bucket`'s running total after a
    successful upload. Every key in these buckets is written once and
    never resized in place, so a plain increment stays accurate between
    `reconcile()` runs."""
    with session_scope() as session:
        stmt = insert(StorageUsage).values(
            bucket=bucket, total_bytes=additional_bytes, object_count=1
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[StorageUsage.bucket],
            set_={
                "total_bytes": StorageUsage.total_bytes + stmt.excluded.total_bytes,
                "object_count": StorageUsage.object_count + 1,
            },
        )
        session.execute(stmt)


def reconcile(bucket: str) -> tuple[int, int]:
    """Recompute `bucket`'s actual size/object count directly from R2 and
    overwrite the stored total -- the source of truth, correcting any
    drift `record_bytes()`'s incremental counter accumulated (a failed
    upload that still got counted, the initial migration's objects, which
    arrive outside the normal upload() path, ...). Returns
    (total_bytes, object_count)."""
    total_bytes, object_count = r2_storage.bucket_totals(bucket)
    with session_scope() as session:
        stmt = insert(StorageUsage).values(
            bucket=bucket, total_bytes=total_bytes, object_count=object_count
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[StorageUsage.bucket],
            set_={"total_bytes": total_bytes, "object_count": object_count},
        )
        session.execute(stmt)
    return total_bytes, object_count
