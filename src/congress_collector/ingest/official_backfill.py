"""One-time backfill of House and Senate PTR filing indices back to the
STOCK Act's electronic-filing era (T20).

Unlike the live sync steps in collect.yml (`ingest.house.sync_house_index`,
`ingest.senate.sync_senate_ptr_index`), which record `first_seen_at` as the
moment the collector itself observed a new filing, backfilled rows use
`ingest.house.backfill_house_year` / `ingest.senate.backfill_senate_since`,
which derive `first_seen_at` from each filing's own filed/submitted date
instead -- claiming "detected within 5 minutes" for a filing from 2013
would be false and would corrupt exactly the timing data this whole
project exists to protect (see README's "Why first seen matters").

Only backfills the filings index itself -- the existing pipeline steps
(`house_pdfs`, `house_ptrs`, `senate_ptrs`, `politician_links`, `tickers`,
`amendments`) already work as a generic backlog over every filing
regardless of age (each selects on a status column, not a date range), so
once this runs, the regular collect.yml cadence picks up
archiving/parsing/linking the backfilled rows over subsequent runs the
same as any other pending filing.

Idempotent and resumable like every other sync step here: new-ness is
decided by filing_id, so a failed or interrupted run can just be
re-triggered and picks up where it left off. Run manually via
`backfill-official.yml` (workflow_dispatch only) -- not part of the
regular collect.yml cadence, since this is a one-time (or rare) operation.
"""

from datetime import UTC, date, datetime

from congress_collector.ingest.house import backfill_house_year
from congress_collector.ingest.senate import backfill_senate_since

# STOCK Act's electronic PTR era. Matches ingest.tickers.DEFAULT_VALID_FROM,
# which already anchors on this as "the earliest date the plan's furthest-
# back backfill period (T20/T21) reaches".
BACKFILL_START_YEAR = 2012


def backfill_all(*, start_year: int = BACKFILL_START_YEAR) -> tuple[int, int]:
    """Backfill both chambers from `start_year` through the current year.
    Returns (house_new_count, senate_new_count)."""
    house_total = 0
    for year in range(start_year, datetime.now(UTC).year + 1):
        count = backfill_house_year(year)
        print(f"House {year}: {count} new filing(s).")
        house_total += count

    senate_total = backfill_senate_since(date(start_year, 1, 1))
    print(f"Senate since {start_year}-01-01: {senate_total} new filing(s).")

    return house_total, senate_total


def main() -> None:
    house_total, senate_total = backfill_all()
    print(f"Official backfill complete: {house_total} House, {senate_total} Senate new filing(s).")


if __name__ == "__main__":
    main()
