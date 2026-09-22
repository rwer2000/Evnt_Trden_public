"""One-off catch-up: drain the House PTR archive/parse/link backlog in one
run instead of collect.yml's drip-fed 25-50/run.

Not part of the regular collect.yml pipeline. Run manually via
workflow_dispatch (catchup-house-backlog.yml) when there's a large
backlog -- e.g. right after T20's backfill added ~46k historical House
filings in one shot, whose ~7,300 PTRs were competing for the same
50-per-run PDF-archiving budget as ~40k non-PTR filing types that never
get parsed at all (see house_pdfs.py's filing_type priority fix).

Each stage's drain loop stops when its own count_pending() reaches 0, not
when a batch's *successful* count hits 0 -- those aren't the same thing.
A batch can process real work (archive fetches that fail and get flagged,
transactions that turn out unmatchable) while still returning 0 for
"succeeded", and stopping on that alone previously made a catch-up run
mislabel itself "done" at 3,226/7,666 PTRs archived (see house_pdfs.py's
_fetch_pending() docstring). Every stage is a plain DB-driven loop with no
external rate limit to respect (House Clerk's PDF server, unlike
Senate/SEC, hasn't shown any blocking in this project), so it's safe to
re-run if a prior run got cut off by the job timeout -- it just picks up
wherever the DB says is left.
"""

from collections.abc import Callable

from congress_collector.ingest.house_pdfs import archive_pending_house_pdfs
from congress_collector.ingest.house_pdfs import count_pending as count_pending_archive
from congress_collector.ingest.house_ptrs import count_pending as count_pending_parse
from congress_collector.ingest.house_ptrs import parse_pending_house_ptrs
from congress_collector.ingest.politician_links import count_pending as count_pending_politicians
from congress_collector.ingest.politician_links import link_pending_filings
from congress_collector.ingest.tickers import count_pending as count_pending_tickers
from congress_collector.ingest.tickers import link_pending_transactions

BATCH_SIZE = 200


def catch_up(*, batch_size: int = BATCH_SIZE) -> None:
    _drain(
        "Archived",
        count_pending_archive,
        lambda: archive_pending_house_pdfs(batch_size=batch_size),
    )
    _drain(
        "Parsed",
        count_pending_parse,
        lambda: len(parse_pending_house_ptrs(batch_size=batch_size)),
    )
    _drain(
        "Linked politicians for",
        count_pending_politicians,
        lambda: link_pending_filings(batch_size=batch_size),
    )
    _drain(
        "Linked tickers for",
        count_pending_tickers,
        lambda: link_pending_transactions(batch_size=batch_size),
    )


def _drain(label: str, count_pending: Callable[[], int], step: Callable[[], int]) -> None:
    total = 0
    while True:
        pending_before = count_pending()
        if pending_before == 0:
            print(f"{label}: nothing pending. Done (running total {total}).")
            break

        count = step()
        total += count
        pending_after = count_pending()
        print(
            f"{label} {count} (running total {total}); "
            f"{pending_after} still pending (was {pending_before})."
        )
        if pending_after >= pending_before:
            print(
                f"{label}: stopping -- {pending_after} filing(s)/transaction(s) still pending "
                "but this batch made no progress against them (likely permanent failures, "
                "e.g. a PDF no longer served). See dq_issues for details."
            )
            break


def main() -> None:
    catch_up()


if __name__ == "__main__":
    main()
