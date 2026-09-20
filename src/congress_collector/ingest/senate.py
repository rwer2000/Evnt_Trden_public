"""Detect new Senate PTR filings and persist them."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

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
        new_count = _insert_new_filings(entries, precision_s)
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


def main() -> None:
    new_count = sync_senate_ptr_index()
    print(f"Senate PTR index sync: {new_count} new filing(s).")


def _insert_new_filings(entries: Sequence[SenateIndexEntry], precision_s: int) -> int:
    with session_scope() as session:
        candidate_ids = [filing_id_for(e.report_uuid) for e in entries]
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )
        to_insert = new_entries(entries, existing)
        now = datetime.now(UTC)
        session.add_all(
            Filing(
                filing_id=filing_id_for(e.report_uuid),
                chamber="senate",
                filer_name=filer_name_for(e),
                filing_type="P",
                filed_date=e.filed_date,
                first_seen_at=now,
                first_seen_precision_s=precision_s,
                format="electronic" if e.is_electronic else "paper",
                parse_status="pending" if e.is_electronic else "paper_deferred",
                source="official",
            )
            for e in to_insert
        )
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
