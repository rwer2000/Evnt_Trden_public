"""Detect new House filings from the yearly index and persist them."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from congress_collector.db.models import Filing, ScrapeRun
from congress_collector.db.session import session_scope
from congress_collector.notify.telegram import send_message
from congress_collector.sources.house import (
    HouseIndexEntry,
    fetch_index,
    filer_name_for,
    filing_id_for,
    pdf_url_for,
)

# Matches the primary external cron cadence (every 5 min on market hours);
# callers running on a different cadence (e.g. the hourly schedule
# fallback) should pass a larger value.
DEFAULT_PRECISION_S = 300

# Cap on how many filer names a single new-filing Telegram message lists,
# so an unusual burst (a catch-up after downtime, say) doesn't produce a
# wall of text -- the count in the message header already says how many
# there really were.
NOTIFY_MAX_LINES = 15

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
    """Entries whose filing_id isn't already in `existing_filing_ids`,
    deduplicated by filing_id (keeping the first occurrence) in case the
    same DocID appears more than once in a single fetch -- confirmed live
    during T20's backfill that a full year's Clerk index can contain
    duplicate <Member> entries for the same DocID, which would otherwise
    reach session.add_all() twice and violate the primary key."""
    seen: set[str] = set()
    result = []
    for e in entries:
        fid = filing_id_for(e.doc_id)
        if fid in existing_filing_ids or fid in seen:
            continue
        seen.add(fid)
        result.append(e)
    return result


def sync_house_index(year: int, *, precision_s: int = DEFAULT_PRECISION_S) -> int:
    """Fetch the House index for `year`, insert newly observed filings,
    send a Telegram notification for them (T12), and record a scrape_runs
    row regardless of outcome. Returns the number of new filings
    inserted."""
    started_at = datetime.now(UTC)
    status = "failed"
    new_count = 0
    error_message: str | None = None

    try:
        entries = fetch_index(year)
        now = datetime.now(UTC)
        inserted = _insert_new_filings(entries, first_seen_for=lambda _e: (now, precision_s))
        new_count = len(inserted)
        status = "success"
        if inserted:
            notify_new_filings(inserted)
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
        new_count = len(_insert_new_filings(entries, first_seen_for=backfill_first_seen))
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


def _insert_new_filings(
    entries: Sequence[HouseIndexEntry], *, first_seen_for: FirstSeenFor
) -> list[HouseIndexEntry]:
    """Insert `entries` not already in `filings`, tolerating a concurrent
    writer beating us to one of the same filing_ids -- confirmed live
    (2026-09-21, scrape_runs): a manually-triggered backfill-official run
    (no shared concurrency group with collect.yml) and a live
    sync_house_index() run both decided the same filing_id was new and
    both tried to INSERT it. Without ON CONFLICT DO NOTHING, one multi-row
    INSERT statement is all-or-nothing, so that single collision rolled
    back every other genuinely-new filing in the same batch too and
    crashed the whole process on an unhandled UniqueViolation. RETURNING
    reports back only the rows this statement actually inserted, so a
    filing the other writer won the race on is excluded from the return
    value (and so from the new-filing notification) rather than being
    reported as inserted twice."""
    with session_scope() as session:
        candidate_ids = [filing_id_for(e.doc_id) for e in entries]
        existing = set(
            session.scalars(select(Filing.filing_id).where(Filing.filing_id.in_(candidate_ids)))
        )
        to_insert = new_entries(entries, existing)
        if not to_insert:
            return []
        rows = []
        for e in to_insert:
            first_seen_at, precision_s = first_seen_for(e)
            rows.append(
                {
                    "filing_id": filing_id_for(e.doc_id),
                    "chamber": "house",
                    "filer_name": filer_name_for(e),
                    "filing_type": e.filing_type,
                    "filed_date": e.filing_date,
                    "first_seen_at": first_seen_at,
                    "first_seen_precision_s": precision_s,
                    "format": "unknown",
                    "source": "official",
                }
            )
        stmt = (
            pg_insert(Filing)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[Filing.filing_id])
            .returning(Filing.filing_id)
        )
        inserted_ids = set(session.scalars(stmt).all())
        return [e for e in to_insert if filing_id_for(e.doc_id) in inserted_ids]


def notify_new_filings(entries: Sequence[HouseIndexEntry]) -> None:
    lines = [
        f"{filer_name_for(e)} ({e.filing_type}) — {pdf_url_for(e.doc_id, e.filing_type, e.year)}"
        for e in entries[:NOTIFY_MAX_LINES]
    ]
    remaining = len(entries) - len(lines)
    if remaining > 0:
        lines.append(f"...and {remaining} more")
    text = f"House: {len(entries)} new filing(s)\n" + "\n".join(lines)
    try:
        send_message(text, category="filing")
    except Exception as exc:
        # Best-effort: a Telegram outage must never break ingestion, the
        # one thing this function absolutely cannot fail to do.
        print(f"Failed to send new-filing notification: {exc}")


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
