"""Detect new Senate PTR filings and persist them."""

from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from congress_collector.db.models import Filing, ScrapeRun
from congress_collector.db.session import session_scope
from congress_collector.sources.senate import (
    SenateIndexEntry,
    fetch_ptr_index,
    filer_name_for,
    filing_id_for,
    new_session,
)

DEFAULT_PRECISION_S = 300
# Wider than the run cadence, per the plan (live: last 14 days), so a
# missed or failed run doesn't silently drop filings -- new-ness is
# decided by filing_id, so re-seeing the same report UUID is a no-op.
LOOKBACK_DAYS = 14

# T20 backfill only: filed_date is day-granularity, so that's the honest
# precision for a first_seen_at derived from it -- see backfill_senate_since.
BACKFILL_DAY_PRECISION_S = 86_400
# T20 backfill only: the rare entry with no filed_date at all has no time
# anchor better than "now" (the backfill run itself), which isn't real
# detection-latency data -- this sentinel (~10 years) flags that fallback
# as meaningless for latency analysis rather than silently understating it.
BACKFILL_UNKNOWN_DATE_PRECISION_S = 315_360_000
# A multi-year backfill can return thousands of rows in one fetch; commit
# in chunks rather than one giant transaction against the pooler.
BACKFILL_CHUNK_SIZE = 500

FirstSeenFor = Callable[[SenateIndexEntry], tuple[datetime, int]]


def new_entries(
    entries: Sequence[SenateIndexEntry], existing_filing_ids: set[str]
) -> list[SenateIndexEntry]:
    """Entries whose filing_id isn't already in `existing_filing_ids`."""
    return [e for e in entries if filing_id_for(e.report_uuid) not in existing_filing_ids]


def sync_senate_ptr_index(*, precision_s: int = DEFAULT_PRECISION_S) -> int:
    """Fetch recent Senate PTR filings, insert newly observed ones, and
    record a scrape_runs row regardless of outcome. Returns the number of
    new filings inserted."""
    started_at = datetime.now(UTC)
    status = "failed"
    new_count = 0
    error_message: str | None = None

    try:
        session = new_session()
        submitted_start = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).date()
        entries = fetch_ptr_index(session, submitted_start=submitted_start)
        now = datetime.now(UTC)
        new_count = _insert_new_filings(entries, first_seen_for=lambda _e: (now, precision_s))
        status = "success"
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _record_scrape_run(
            chamber="senate",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status=status,
            new_filings_count=new_count,
            error_message=error_message,
        )

    return new_count


def backfill_senate_since(submitted_start: date) -> int:
    """Backfill historical Senate PTR filings submitted on/after
    `submitted_start` (T20). Unlike `sync_senate_ptr_index` (live
    monitoring), first_seen_at is derived from each entry's own submitted
    date rather than "now" -- see `house.backfill_house_year`'s matching
    note on why. Records a scrape_runs row like the live sync does, and
    commits in chunks since a multi-year fetch can return thousands of
    rows in one call."""
    started_at = datetime.now(UTC)
    status = "failed"
    new_count = 0
    error_message: str | None = None

    try:
        session = new_session()
        entries = fetch_ptr_index(session, submitted_start=submitted_start)
        for chunk in _chunked(entries, BACKFILL_CHUNK_SIZE):
            new_count += _insert_new_filings(chunk, first_seen_for=backfill_first_seen)
        status = "success"
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _record_scrape_run(
            chamber="senate",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status=status,
            new_filings_count=new_count,
            error_message=error_message,
        )

    return new_count


def backfill_first_seen(entry: SenateIndexEntry) -> tuple[datetime, int]:
    """(first_seen_at, first_seen_precision_s) for a backfilled entry,
    derived from its own submitted date rather than "now"."""
    if entry.filed_date is None:
        return datetime.now(UTC), BACKFILL_UNKNOWN_DATE_PRECISION_S
    return datetime.combine(entry.filed_date, time.min, tzinfo=UTC), BACKFILL_DAY_PRECISION_S


def _chunked(
    entries: Sequence[SenateIndexEntry], size: int
) -> Iterator[Sequence[SenateIndexEntry]]:
    for start in range(0, len(entries), size):
        yield entries[start : start + size]


def main() -> None:
    new_count = sync_senate_ptr_index()
    print(f"Senate PTR index sync: {new_count} new filing(s).")


def _insert_new_filings(
    entries: Sequence[SenateIndexEntry], *, first_seen_for: FirstSeenFor
) -> int:
    with session_scope() as session:
        candidate_ids = [filing_id_for(e.report_uuid) for e in entries]
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )
        to_insert = new_entries(entries, existing)
        rows = []
        for e in to_insert:
            first_seen_at, precision_s = first_seen_for(e)
            rows.append(
                Filing(
                    filing_id=filing_id_for(e.report_uuid),
                    chamber="senate",
                    filer_name=filer_name_for(e),
                    filing_type="P",
                    filed_date=e.filed_date,
                    first_seen_at=first_seen_at,
                    first_seen_precision_s=precision_s,
                    format="electronic" if e.is_electronic else "paper",
                    parse_status="pending" if e.is_electronic else "paper_deferred",
                    source="official",
                )
            )
        session.add_all(rows)
        return len(to_insert)


def _record_scrape_run(
    *,
    chamber: str,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    new_filings_count: int,
    error_message: str | None,
) -> None:
    with session_scope() as session:
        session.add(
            ScrapeRun(
                chamber=chamber,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                new_filings_count=new_filings_count,
                error_message=error_message,
            )
        )


if __name__ == "__main__":
    main()
