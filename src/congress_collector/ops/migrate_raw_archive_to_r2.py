"""One-time migration: copy the `congress-raw` and `congress-backups`
buckets from Supabase Storage to Cloudflare R2 (see README's "Database &
storage" section for why -- the raw archive outgrew Supabase's free 1 GB
Storage quota, shared with the unrelated Sportlogging app; Postgres itself
was nowhere near its own, separate 500 MB quota and stayed put).

Not part of the regular collect.yml pipeline. Run manually
(`uv run python -m congress_collector.ops.migrate_raw_archive_to_r2`) once,
with both the Supabase Storage credentials (source) and the R2 credentials
(destination) set. Safe to re-run: for the raw archive, `existing_sha256()`
checks R2's stored hash against `filings.raw_sha256` -- already-migrated
Postgres source of truth, so this doesn't need to download it from Supabase
just to confirm that, unlike the small `congress-backups` bucket (no stored
hash anywhere), where presence in R2 alone is enough to skip a key: backup
object names are date-stamped and never rewritten with different content.
"""

import logging

from sqlalchemy import select

from congress_collector.db.models import Filing
from congress_collector.db.session import session_scope
from congress_collector.storage import r2_storage, supabase_storage

logger = logging.getLogger(__name__)

RAW_BUCKET = "congress-raw"
BACKUP_BUCKET = "congress-backups"

_CONTENT_TYPES = {".pdf": "application/pdf", ".html": "text/html", ".gz": "application/gzip"}


def _content_type_for(key: str) -> str:
    for suffix, content_type in _CONTENT_TYPES.items():
        if key.endswith(suffix):
            return content_type
    return "application/octet-stream"


def _raw_archive_entries() -> list[tuple[str, str | None]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.raw_object_key, Filing.raw_sha256).where(
                Filing.raw_object_key.is_not(None)
            )
        ).all()
        return [(key, sha) for key, sha in rows if key]


def migrate_raw_archive(entries: list[tuple[str, str | None]]) -> tuple[int, int, list[str]]:
    """Returns (copied, already_present, failed_keys)."""
    copied = already_present = 0
    failed: list[str] = []
    for i, (key, expected_sha256) in enumerate(entries, 1):
        if r2_storage.existing_sha256(key, bucket=RAW_BUCKET) == expected_sha256:
            already_present += 1
        else:
            try:
                content = supabase_storage.download(key, bucket=RAW_BUCKET)
                r2_storage.upload(key, content, _content_type_for(key), bucket=RAW_BUCKET)
                copied += 1
            except Exception as exc:
                logger.error("raw archive: failed to migrate %s: %s", key, exc)
                failed.append(key)

        if i % 1000 == 0:
            logger.info("raw archive: %d/%d checked", i, len(entries))

    return copied, already_present, failed


def _backup_keys() -> list[str]:
    client = supabase_storage.get_client()
    entries = client.storage.from_(BACKUP_BUCKET).list()
    return [entry["name"] for entry in entries if entry.get("name")]


def migrate_backups(keys: list[str]) -> tuple[int, int, list[str]]:
    """Returns (copied, already_present, failed_keys)."""
    copied = already_present = 0
    failed: list[str] = []
    for key in keys:
        if r2_storage.existing_sha256(key, bucket=BACKUP_BUCKET) is not None:
            already_present += 1
            continue
        try:
            content = supabase_storage.download(key, bucket=BACKUP_BUCKET)
            r2_storage.upload(key, content, _content_type_for(key), bucket=BACKUP_BUCKET)
            copied += 1
        except Exception as exc:
            logger.error("backups: failed to migrate %s: %s", key, exc)
            failed.append(key)
    return copied, already_present, failed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    raw_entries = _raw_archive_entries()
    logger.info("raw archive: %d object(s) to check", len(raw_entries))
    raw_copied, raw_present, raw_failed = migrate_raw_archive(raw_entries)
    logger.info(
        "raw archive: %d copied, %d already in R2, %d failed",
        raw_copied,
        raw_present,
        len(raw_failed),
    )

    backup_keys = _backup_keys()
    logger.info("backups: %d object(s) to check", len(backup_keys))
    backup_copied, backup_present, backup_failed = migrate_backups(backup_keys)
    logger.info(
        "backups: %d copied, %d already in R2, %d failed",
        backup_copied,
        backup_present,
        len(backup_failed),
    )

    for label, failed in (("raw archive", raw_failed), ("backups", backup_failed)):
        if failed:
            logger.warning("%s: failed key(s): %s", label, ", ".join(failed[:20]))


if __name__ == "__main__":
    main()
