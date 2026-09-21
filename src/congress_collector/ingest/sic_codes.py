"""Sync `instruments.sic`/`sic_description` from SEC EDGAR (T24).

One HTTP request per instrument still missing a SIC sync
(`sic_synced_at IS NULL`), throttled well under SEC's stated fair-access
rate limits (https://www.sec.gov/os/webmaster-faq#developers asks for no
more than 10 requests/second; this sleeps `REQUEST_INTERVAL_S` between
requests, an order of magnitude under that). Runs as its own periodic
workflow rather than a collect.yml step: SIC codes change essentially
never once set, and this only needs to catch up with however many new
instruments T14 created since the last run -- a handful per day in
practice, not the full ~800-instrument universe.
"""

import time
from datetime import UTC, datetime

from sqlalchemy import select

from congress_collector.db.models import Instrument
from congress_collector.db.session import session_scope
from congress_collector.sources.sec_submissions import fetch_sic, new_client

BATCH_SIZE = 200
REQUEST_INTERVAL_S = 0.5


def sync_sic_codes(*, batch_size: int = BATCH_SIZE) -> int:
    """Fetch+store a SIC code for up to `batch_size` instruments that
    haven't been synced yet. Returns the number of instruments touched
    (whether or not SEC had a SIC for them)."""
    with session_scope() as session:
        pending_pairs = list(
            session.execute(
                select(Instrument.instrument_id, Instrument.cik)
                .where(Instrument.cik.is_not(None), Instrument.sic_synced_at.is_(None))
                .limit(batch_size)
            )
        )

    if not pending_pairs:
        return 0

    client = new_client()
    try:
        touched = 0
        for instrument_id, cik in pending_pairs:
            record = fetch_sic(cik, client=client)
            with session_scope() as session:
                instrument = session.get(Instrument, instrument_id)
                if instrument is not None:
                    instrument.sic = record.sic if record else None
                    instrument.sic_description = record.sic_description if record else None
                    instrument.sic_synced_at = datetime.now(UTC)
            touched += 1
            time.sleep(REQUEST_INTERVAL_S)
        return touched
    finally:
        client.close()


def main() -> None:
    touched = sync_sic_codes()
    print(f"SIC code sync: {touched} instrument(s) synced.")


if __name__ == "__main__":
    main()
