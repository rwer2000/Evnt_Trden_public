"""Import House/Senate Stock Watcher into `community_transactions` and
measure survivorship bias against our own `filings` table (T21).

A community record's `matched_filing_id` is set when its `external_filing_id`
(our own filing_id format -- see `sources.community_archive`) already exists
in `filings`; left NULL otherwise. A community filing_id with no match is
exactly the survivorship-bias signal the plan calls for: something a
community scraper observed at some point that the official site no longer
surfaces (or that our own backfill/collector hasn't reached yet -- see
`rematch_unmatched`, which re-checks previously-unmatched rows on every run
so the signal stays accurate as our own coverage grows, rather than
freezing whatever was true at the moment of the original import).

Not part of the regular collect.yml cadence: run manually via the
`import-community-archive` workflow (`workflow_dispatch` only) or
`uv run python -m congress_collector.ingest.community_archive`. Idempotent
-- re-importing the same source data is a no-op past the first run, since
new-ness is decided by a content hash (`dedup_key_for`), not a natural ID
neither dataset provides per row.
"""

import hashlib
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from congress_collector.db.models import CommunityTransaction, Filing
from congress_collector.db.session import session_scope
from congress_collector.sources.community_archive import (
    HOUSE_SOURCE,
    SENATE_SOURCE,
    CommunityRecord,
    fetch_house_stock_watcher,
    fetch_senate_stock_watcher,
)

# A multi-thousand-row import shouldn't be one giant transaction against
# the pooler -- commit in chunks, same reasoning as T20's Senate backfill.
IMPORT_CHUNK_SIZE = 500


def dedup_key_for(record: CommunityRecord) -> str:
    """A stable content hash standing in for a per-row ID neither
    dataset provides -- re-importing the same source snapshot must not
    create duplicates."""
    parts = [
        record.external_filing_id or "",
        record.filer_name or "",
        record.tx_date.isoformat() if record.tx_date else "",
        record.ticker or "",
        record.asset_description or "",
        record.tx_type or "",
        record.owner or "",
        "" if record.amount_min is None else repr(record.amount_min),
        "" if record.amount_max is None else repr(record.amount_max),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def import_records(records: Sequence[CommunityRecord], source: str) -> int:
    """Insert records from `source` not already present (by content
    hash). Returns the number of rows actually inserted."""
    imported = 0
    for start in range(0, len(records), IMPORT_CHUNK_SIZE):
        imported += _import_chunk(records[start : start + IMPORT_CHUNK_SIZE], source)
    return imported


def _import_chunk(chunk: Sequence[CommunityRecord], source: str) -> int:
    with session_scope() as session:
        existing_filing_ids = _existing_filing_ids(session, chunk)
        existing_dedup_keys = set(
            session.scalars(
                select(CommunityTransaction.dedup_key).where(CommunityTransaction.source == source)
            )
        )

        rows = []
        seen_in_batch: set[str] = set()
        for record in chunk:
            key = dedup_key_for(record)
            if key in existing_dedup_keys or key in seen_in_batch:
                continue
            seen_in_batch.add(key)
            rows.append(
                CommunityTransaction(
                    source=record.source,
                    chamber=record.chamber,
                    dedup_key=key,
                    external_filing_id=record.external_filing_id,
                    matched_filing_id=(
                        record.external_filing_id
                        if record.external_filing_id in existing_filing_ids
                        else None
                    ),
                    filer_name=record.filer_name,
                    ticker=record.ticker,
                    asset_description=record.asset_description,
                    asset_type=record.asset_type,
                    tx_type=record.tx_type,
                    owner=record.owner,
                    tx_date=record.tx_date,
                    disclosure_date=record.disclosure_date,
                    amount_min=record.amount_min,
                    amount_max=record.amount_max,
                )
            )
        session.add_all(rows)
        return len(rows)


def _existing_filing_ids(session: Session, chunk: Sequence[CommunityRecord]) -> set[str]:
    candidate_ids = {r.external_filing_id for r in chunk if r.external_filing_id}
    if not candidate_ids:
        return set()
    return set(session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids))))


def rematch_unmatched() -> int:
    """Re-check every community row still missing a match -- our own
    backfill/collector coverage grows over time, so a row unmatched
    yesterday may be matched today. Returns the number newly matched."""
    with session_scope() as session:
        pending = session.scalars(
            select(CommunityTransaction).where(
                CommunityTransaction.matched_filing_id.is_(None),
                CommunityTransaction.external_filing_id.is_not(None),
            )
        ).all()
        if not pending:
            return 0

        candidate_ids = {ct.external_filing_id for ct in pending if ct.external_filing_id}
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )

        updated = 0
        for ct in pending:
            if ct.external_filing_id in existing:
                ct.matched_filing_id = ct.external_filing_id
                updated += 1
        return updated


def survivorship_report() -> dict[str, dict[str, int]]:
    """Per source: how many distinct filings the community archive
    recorded that our own `filings` table does/doesn't have."""
    with session_scope() as session:
        rows = session.execute(
            select(
                CommunityTransaction.source,
                CommunityTransaction.external_filing_id,
                CommunityTransaction.matched_filing_id,
            )
            .where(CommunityTransaction.external_filing_id.is_not(None))
            .distinct()
        ).all()

    report: dict[str, dict[str, int]] = {}
    for source, _external_filing_id, matched_filing_id in rows:
        bucket = report.setdefault(source, {"matched": 0, "unmatched": 0})
        bucket["matched" if matched_filing_id is not None else "unmatched"] += 1
    return report


def main() -> None:
    house_records = fetch_house_stock_watcher()
    house_imported = import_records(house_records, HOUSE_SOURCE)
    print(f"House Stock Watcher: {len(house_records)} fetched, {house_imported} new.")

    senate_records = fetch_senate_stock_watcher()
    senate_imported = import_records(senate_records, SENATE_SOURCE)
    print(f"Senate Stock Watcher: {len(senate_records)} fetched, {senate_imported} new.")

    rematched = rematch_unmatched()
    print(f"Re-matched {rematched} previously-unmatched row(s) against current filings.")

    for source, counts in survivorship_report().items():
        total = counts["matched"] + counts["unmatched"]
        rate = counts["unmatched"] / total if total else 0.0
        print(
            f"{source}: {counts['matched']}/{total} filings matched to our own records "
            f"({counts['unmatched']} not found, {rate:.1%} potential survivorship gap)"
        )


if __name__ == "__main__":
    main()
