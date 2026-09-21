"""Detect new House filings from the yearly index and persist them."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time

from sqlalchemy import select

from congress_collector.db.models import Filing, ScrapeRun
from congress_collector.db.session import session_scope
from congress_collector.sources.house import (
    HouseIndexEntry,
    fetch_index,
    filer_name_for,
    filing_id_for,
)

# Matches the primary external cron cadence (every 5 min on market hours);
# callers running on a different cadence (e.g. the hourly schedule
# fallback) should pass a larger value.
DEFAULT_PRECISION_S = 300

# T20 backfill only: filed_date is day-granularity, so that's the honest
# precision for a first_seen_at derived from it -- see backfill_house_year.
BACKFILL_DAY_PRECISION_S = 86_400
# T20 backfill only: the rare entry with no filed_date at all has no time
# anchor better than "now" (the backfill run itself), which isn't real
# detection-latency data -- this sentinel (~10 years) flags that fallback
# as meaningless for latency analysis rather than silently understating it.
BACKFILL_UNKNOWN_DATE_PRECISION_S = 315_360_000

FirstSeenFor = Callable[[HouseIndexEntry], tuple[datetime, int]]


def new_entries(
    entries: Sequence[HouseIndexEntry], existing_filing_ids: set[str]
) -> list[HouseIndexEntry]:
    """Entries whose filing_id isn't already in `existing_filing_ids`."""
    return [e for e in entries if filing_id_for(e.doc_id) not in existing_filing_ids]


def sync_house_index(year: int, *, precision_s: int = DEFAULT_PRECISION_S) -> int:
    """Fetch the House index for `year`, insert newly observed filings, and
    record a scrape_runs row regardless of outcome. Returns the number of
    new filings inserted."""
    started_at = datetime.now(UTC)
    status = "failed"
    new_count = 0
    error_message: str | None = None

    try:
        entries = fetch_index(year)
        now = datetime.now(UTC)
        new_count = _insert_new_filings(entries, first_seen_for=lambda _e: (now, precision_s))
        status = "success"
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _record_scrape_run(
            chamber="house",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status=status,
            new_filings_count=new_count,
            error_message=error_message,
        )

    return new_count


def backfill_house_year(year: int) -> int:
    """Backfill historical House filings for `year` from the official
    Clerk index (T20). Unlike `sync_house_index` (live monitoring),
    first_seen_at here is derived from each entry's own filed date rather
    than "now" -- claiming a 2013 filing was detected within 5 minutes
    would be false and would corrupt exactly the timing data this project
    exists to protect (see README's "Why first seen matters"). Records a
    scrape_runs row like the live sync does."""
    started_at = datetime.now(UTC)
    status = "failed"
    new_count = 0
    error_message: str | None = None

    try:
        entries = fetch_index(year)
        new_count = _insert_new_filings(entries, first_seen_for=backfill_first_seen)
        status = "success"
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        _record_scrape_run(
            chamber="house",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            status=status,
            new_filings_count=new_count,
            error_message=error_message,
        )

    return new_count


def backfill_first_seen(entry: HouseIndexEntry) -> tuple[datetime, int]:
    """(first_seen_at, first_seen_precision_s) for a backfilled entry,
    derived from its own filed date rather than "now"."""
    if entry.filing_date is None:
        return datetime.now(UTC), BACKFILL_UNKNOWN_DATE_PRECISION_S
    return datetime.combine(entry.filing_date, time.min, tzinfo=UTC), BACKFILL_DAY_PRECISION_S


def _insert_new_filings(entries: Sequence[HouseIndexEntry], *, first_seen_for: FirstSeenFor) -> int:
    with session_scope() as session:
        candidate_ids = [filing_id_for(e.doc_id) for e in entries]
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )
        to_insert = new_entries(entries, existing)
        rows = []
        for e in to_insert:
            first_seen_at, precision_s = first_seen_for(e)
            rows.append(
                Filing(
                    filing_id=filing_id_for(e.doc_id),
                    chamber="house",
                    filer_name=filer_name_for(e),
                    filing_type=e.filing_type,
                    filed_date=e.filing_date,
                    first_seen_at=first_seen_at,
                    first_seen_precision_s=precision_s,
                    format="unknown",
                    source="official",
                )
            )
        session.add_all(rows)
        return len(to_insert)


def main() -> None:
    year = datetime.now(UTC).year
    new_count = sync_house_index(year)
    print(f"House index sync ({year}): {new_count} new filing(s).")


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
