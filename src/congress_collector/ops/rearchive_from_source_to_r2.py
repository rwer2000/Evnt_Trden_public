"""Re-fetch every already-archived filing directly from its original public
source (House Clerk / Senate eFD) and write it straight to R2, bypassing
Supabase Storage entirely.

Supabase started returning 402 Payment Required project-wide on
2026-09-28 (the free Storage/bandwidth tier exceeded) -- which blocks
`migrate_raw_archive_to_r2`'s reads from `congress-raw`, and, it turned
out, every Supabase Data-API call (Storage *and* PostgREST), not just
Storage. Direct Postgres connections (`DATABASE_URL`, what
`db.session` and every other module in this repo actually use) kept
working throughout, which is what makes this recovery possible at all:
the list of what to re-fetch, and the source identifiers to fetch it
with, are still fully queryable.

Since every archived file is, by design, nothing but a byte-exact copy of
a public document, the archive isn't actually lost to the 402 -- it can
be re-derived from the same public sources `house_pdfs.py`/`senate_ptrs.py`
already fetch from for newly-discovered filings, this time landing
directly in R2. `raw_object_key` already encodes exactly where each file
needs to land (`house/{year}/{doc_id}.pdf`, `senate/{report_uuid}.html`),
so the year comes from parsing that key back apart rather than from
`filings.filed_date` (nullable, and not guaranteed to match the year the
original archive step used if it were ever recomputed).

Resumable the same way `migrate_raw_archive_to_r2` is: skips a key
already in R2 with a matching SHA-256.

House gets no added delay between requests, matching `house_pdfs.py`'s
and `catchup_house_backlog.py`'s existing behavior at similar scale.
Senate gets `time.sleep(1.0)` between requests -- efdsearch.senate.gov's
documented policy (see `sources/senate.py`'s module docstring) is ~1
request/second, and re-fetching thousands of reports in a tight loop is
exactly the kind of burst that policy exists to prevent.
"""

import logging
import time

import httpx
from sqlalchemy import select

from congress_collector.db.models import Filing
from congress_collector.db.session import session_scope
from congress_collector.sources.house import USER_AGENT as HOUSE_USER_AGENT
from congress_collector.sources.house import pdf_url_for
from congress_collector.sources.senate import new_session, ptr_url_for
from congress_collector.storage import quota, r2_storage

logger = logging.getLogger(__name__)

SENATE_REQUEST_DELAY_S = 1.0


def _year_from_object_key(object_key: str) -> int:
    # "house/{year}/{doc_id}.pdf"
    return int(object_key.split("/")[1])


def house_entries() -> list[tuple[str, str, str, int]]:
    """(object_key, doc_id, filing_type, year) for every archived House filing."""
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key, Filing.filing_type).where(
                Filing.chamber == "house", Filing.raw_object_key.is_not(None)
            )
        ).all()
        return [
            (
                object_key,
                filing_id.removeprefix("house:"),
                filing_type,
                _year_from_object_key(object_key),
            )
            for filing_id, object_key, filing_type in rows
            if object_key
        ]


def senate_entries() -> list[tuple[str, str]]:
    """(object_key, report_uuid) for every archived Senate filing."""
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key).where(
                Filing.chamber == "senate", Filing.raw_object_key.is_not(None)
            )
        ).all()
        return [
            (object_key, filing_id.removeprefix("senate:"))
            for filing_id, object_key in rows
            if object_key
        ]


def _update_sha256(filing_id: str, sha256: str) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is not None:
            filing.raw_sha256 = sha256


def rearchive_house(entries: list[tuple[str, str, str, int]]) -> tuple[int, int, list[str]]:
    """Returns (copied, already_present, failed_keys)."""
    copied = already_present = 0
    failed: list[str] = []
    client = httpx.Client(
        follow_redirects=True, timeout=30.0, headers={"User-Agent": HOUSE_USER_AGENT}
    )
    try:
        for i, (object_key, doc_id, filing_type, year) in enumerate(entries, 1):
            if r2_storage.existing_sha256(object_key, bucket=r2_storage.BUCKET) is not None:
                already_present += 1
            else:
                url = pdf_url_for(doc_id, filing_type, year)
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    content = response.content
                    quota.ensure_budget(r2_storage.BUCKET, len(content))
                    r2_storage.upload(object_key, content, "application/pdf")
                    quota.record_bytes(r2_storage.BUCKET, len(content))
                    _update_sha256(f"house:{doc_id}", r2_storage.sha256_hex(content))
                    copied += 1
                except Exception as exc:
                    logger.error("house: failed to re-archive %s (%s): %s", object_key, url, exc)
                    failed.append(object_key)

            if i % 500 == 0:
                logger.info("house: %d/%d checked", i, len(entries))
    finally:
        client.close()
    return copied, already_present, failed


def rearchive_senate(entries: list[tuple[str, str]]) -> tuple[int, int, list[str]]:
    """Returns (copied, already_present, failed_keys)."""
    copied = already_present = 0
    failed: list[str] = []
    session = new_session()
    for i, (object_key, report_uuid) in enumerate(entries, 1):
        if r2_storage.existing_sha256(object_key, bucket=r2_storage.BUCKET) is not None:
            already_present += 1
        else:
            url = ptr_url_for(report_uuid)
            try:
                response = session.get(url)
                response.raise_for_status()
                content = response.content
                quota.ensure_budget(r2_storage.BUCKET, len(content))
                r2_storage.upload(object_key, content, "text/html")
                quota.record_bytes(r2_storage.BUCKET, len(content))
                _update_sha256(f"senate:{report_uuid}", r2_storage.sha256_hex(content))
                copied += 1
            except Exception as exc:
                logger.error("senate: failed to re-archive %s (%s): %s", object_key, url, exc)
                failed.append(object_key)
            time.sleep(SENATE_REQUEST_DELAY_S)

        if i % 500 == 0:
            logger.info("senate: %d/%d checked", i, len(entries))
    return copied, already_present, failed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    house = house_entries()
    logger.info("house: %d filing(s) to check", len(house))
    house_copied, house_present, house_failed = rearchive_house(house)
    logger.info(
        "house: %d copied, %d already in R2, %d failed",
        house_copied,
        house_present,
        len(house_failed),
    )

    senate = senate_entries()
    logger.info("senate: %d filing(s) to check", len(senate))
    senate_copied, senate_present, senate_failed = rearchive_senate(senate)
    logger.info(
        "senate: %d copied, %d already in R2, %d failed",
        senate_copied,
        senate_present,
        len(senate_failed),
    )

    for label, failed in (("house", house_failed), ("senate", senate_failed)):
        if failed:
            logger.warning("%s: failed key(s): %s", label, ", ".join(failed[:20]))

    total_bytes, object_count = quota.reconcile(r2_storage.BUCKET)
    logger.info(
        "%s: running total seeded at %d bytes (%d objects)",
        r2_storage.BUCKET,
        total_bytes,
        object_count,
    )


if __name__ == "__main__":
    main()
