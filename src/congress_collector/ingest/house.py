"""Detect new House filings from the yearly index and persist them."""

from collections.abc import Sequence
from datetime import UTC, datetime

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
        new_count = _insert_new_filings(entries, precision_s)
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


def _insert_new_filings(entries: Sequence[HouseIndexEntry], precision_s: int) -> int:
    with session_scope() as session:
        candidate_ids = [filing_id_for(e.doc_id) for e in entries]
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )
        to_insert = new_entries(entries, existing)
        now = datetime.now(UTC)
        session.add_all(
            Filing(
                filing_id=filing_id_for(e.doc_id),
                chamber="house",
                filer_name=filer_name_for(e),
                filing_type=e.filing_type,
                filed_date=e.filing_date,
                first_seen_at=now,
                first_seen_precision_s=precision_s,
                format="unknown",
                source="official",
            )
            for e in to_insert
        )
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
