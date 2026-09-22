"""One-off catch-up: drain the House PTR archive/parse/link backlog in one
run instead of collect.yml's drip-fed 25-50/run.

Not part of the regular collect.yml pipeline. Run manually via
workflow_dispatch (catchup-house-backlog.yml) when there's a large
backlog -- e.g. right after T20's backfill added ~46k historical House
filings in one shot, whose ~7,300 PTRs were competing for the same
50-per-run PDF-archiving budget as ~40k non-PTR filing types that never
get parsed at all (see house_pdfs.py's filing_type priority fix). Every
step here is itself a "process what's pending" loop with no external rate
limit (unlike Senate/SEC), so it's safe to re-run if a prior run got cut
off by the job timeout -- it just picks up wherever the DB says is left.
"""

from collections.abc import Callable

from congress_collector.ingest.house_pdfs import archive_pending_house_pdfs
from congress_collector.ingest.house_ptrs import parse_pending_house_ptrs
from congress_collector.ingest.politician_links import link_pending_filings
from congress_collector.ingest.tickers import link_pending_transactions

BATCH_SIZE = 200


def catch_up(*, batch_size: int = BATCH_SIZE) -> None:
    _drain("Archived", lambda: archive_pending_house_pdfs(batch_size=batch_size))
    _drain("Parsed", lambda: len(parse_pending_house_ptrs(batch_size=batch_size)))
    _drain("Linked politicians for", lambda: link_pending_filings(batch_size=batch_size))
    _drain("Linked tickers for", lambda: link_pending_transactions(batch_size=batch_size))


def _drain(label: str, step: Callable[[], int]) -> None:
    total = 0
    while True:
        count = step()
        total += count
        print(f"{label} {count} (running total {total}).")
        if count == 0:
            break


def main() -> None:
    catch_up()


if __name__ == "__main__":
    main()
