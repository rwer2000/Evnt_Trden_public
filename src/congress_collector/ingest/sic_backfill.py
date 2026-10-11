"""Give every ticker that appears in `transactions` an instrument (and so,
via `ingest/sic_codes.py`, a SIC code) -- including delisted, acquired or
renamed companies that today's `company_tickers.json` snapshot no longer
lists (A3).

T14's linking (`ingest/tickers.py`) only creates instruments for tickers
it can resolve against the vendored current-day SEC snapshot, so a large
share of historically traded tickers (VMW, BRCM, CBI, ...) never got an
instrument and therefore never got a SIC code. For each traded ticker
still without an instrument this step:

1. takes the CIK straight from the vendored snapshot if the ticker is
   listed there (T14 just hasn't linked those transactions yet), else
2. derives the company name(s) from the ticker's raw asset descriptions
   and looks the name up on EDGAR's entity search
   (`sources/sec_company_search.py`), accepting a CIK only on an *exact*
   normalised name match (`parsers/cik_name_match.py`). Ambiguous names
   (several CIKs with the same normalised name) are logged, never guessed.

A resolved CIK that already has an instrument only gets a `ticker_map`
row for the old ticker (one instrument per CIK, as in T14); a new CIK gets
a new `instruments` row with `sic_synced_at` NULL, which the SIC sync at
the end of this run (and the daily `sic-codes.yml`) then fills.

Transactions themselves are not relinked here -- this only adds reference
data; `transactions.instrument_id` stays T14's job.

No persistent "already tried" state: an unmatched ticker is simply
retried on the next run. That's why this runs monthly/on demand
(`.github/workflows/sic-backfill.yml`), not daily -- ~2k name lookups at
`REQUEST_INTERVAL_S` is a ~30 minute, polite job.
"""

import argparse
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select

from congress_collector.db.models import Instrument, TickerMap, Transaction
from congress_collector.db.session import session_scope
from congress_collector.ingest.sic_codes import sync_sic_codes
from congress_collector.ingest.tickers import DEFAULT_VALID_FROM
from congress_collector.parsers.cik_name_match import (
    NameMatch,
    is_equity_like_ticker,
    match_cik_by_name,
    name_from_description,
)
from congress_collector.parsers.ticker_match import normalize_ticker
from congress_collector.sources.sec_company_search import (
    EdgarEntity,
    new_client,
    search_entities,
)
from congress_collector.sources.sec_tickers import load_sec_tickers

REQUEST_INTERVAL_S = 0.5
MAX_NAMES_PER_TICKER = 3
MAX_SIC_SYNC_ROUNDS = 50


@dataclass(frozen=True)
class TickerCandidate:
    ticker: str
    names: tuple[str, ...]  # company names from its descriptions, most common first


def select_candidate_tickers(
    tx_rows: Iterable[tuple[str | None, str, bool]],
    covered_tickers: set[str],
    *,
    max_names: int = MAX_NAMES_PER_TICKER,
) -> list[TickerCandidate]:
    """Every distinct, ticker-shaped `transactions.ticker` that no
    instrument covers yet. `tx_rows` is `(ticker, asset_description_raw,
    has_instrument)`; a ticker counts as covered if it's an instrument's
    primary ticker or in `ticker_map` (`covered_tickers`), or if any of
    its transactions is already linked to an instrument."""
    covered = {normalize_ticker(t) for t in covered_tickers}
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for raw_ticker, description, has_instrument in tx_rows:
        if not raw_ticker or not raw_ticker.strip():
            continue
        ticker = normalize_ticker(raw_ticker)
        if has_instrument:
            covered.add(ticker)
            continue
        if not is_equity_like_ticker(ticker):
            continue
        counter = names[ticker]
        name = name_from_description(description, ticker)
        if name is not None:
            counter[name] += 1

    return [
        TickerCandidate(t, tuple(n for n, _ in names[t].most_common(max_names)))
        for t in sorted(names)
        if t not in covered
    ]


@dataclass
class BackfillReport:
    candidates: int = 0
    from_snapshot: int = 0
    matched_by_name: int = 0
    new_instruments: int = 0
    ticker_map_only: int = 0
    unmatched: int = 0
    no_name: int = 0
    ambiguous: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    aborted: str | None = None


def backfill_traded_tickers(
    *, limit: int | None = None, client: httpx.Client | None = None
) -> BackfillReport:
    with session_scope() as session:
        tx_rows = [
            (ticker, description, bool(linked))
            for ticker, description, linked in session.execute(
                select(
                    Transaction.ticker,
                    Transaction.asset_description_raw,
                    Transaction.instrument_id.is_not(None),
                )
                .where(Transaction.ticker.is_not(None))
                .distinct()
            )
        ]
        covered = {t for t in session.scalars(select(Instrument.primary_ticker)) if t}
        covered |= set(session.scalars(select(TickerMap.ticker)))
        instrument_by_cik: dict[str, uuid.UUID] = {
            cik: iid
            for cik, iid in session.execute(select(Instrument.cik, Instrument.instrument_id))
            if cik
        }

    candidates = select_candidate_tickers(tx_rows, covered)
    if limit is not None:
        candidates = candidates[:limit]
    report = BackfillReport(candidates=len(candidates))
    by_ticker = {c.ticker: c for c in load_sec_tickers()}

    own_client = client is None
    http = client or new_client()
    try:
        for candidate in candidates:
            company = by_ticker.get(candidate.ticker)
            if company is not None:
                report.from_snapshot += 1
                _store(
                    candidate.ticker, company.cik, company.title, "sec", instrument_by_cik, report
                )
                continue
            if not candidate.names:
                report.no_name += 1
                continue

            try:
                match = _lookup(candidate, http)
            except httpx.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                report.aborted = f"{type(exc).__name__} (status {status}) at {candidate.ticker}"
                break

            if match.status == "matched" and match.cik is not None:
                report.matched_by_name += 1
                _store(
                    candidate.ticker,
                    match.cik,
                    match.name,
                    "sec_name_search",
                    instrument_by_cik,
                    report,
                )
            elif match.status == "ambiguous":
                report.ambiguous.append((candidate.ticker, match.candidates))
                print(
                    f"AMBIGUOUS {candidate.ticker}: names={list(candidate.names)} "
                    f"ciks={list(match.candidates)}"
                )
            else:
                report.unmatched += 1
    finally:
        if own_client:
            http.close()
    return report


def _lookup(candidate: TickerCandidate, client: httpx.Client) -> NameMatch:
    hits: list[list[EdgarEntity]] = []
    for name in candidate.names:
        hits.append(search_entities(name, client=client))
        time.sleep(REQUEST_INTERVAL_S)
    return match_cik_by_name(candidate.ticker, candidate.names, hits)


def _store(
    ticker: str,
    cik: str,
    name: str | None,
    source: str,
    instrument_by_cik: dict[str, uuid.UUID],
    report: BackfillReport,
) -> None:
    with session_scope() as session:
        instrument_id = instrument_by_cik.get(cik)
        if instrument_id is None:
            instrument_id = uuid.uuid4()
            session.add(
                Instrument(
                    instrument_id=instrument_id,
                    primary_ticker=ticker,
                    cik=cik,
                    name=name,
                    asset_class="equity",
                )
            )
            instrument_by_cik[cik] = instrument_id
            report.new_instruments += 1
        else:
            report.ticker_map_only += 1
        session.add(
            TickerMap(
                ticker_map_id=uuid.uuid4(),
                instrument_id=instrument_id,
                ticker=ticker,
                valid_from=DEFAULT_VALID_FROM,
                valid_to=None,
                source=source,
            )
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--limit", type=int, default=None, help="max candidate tickers this run")
    args = parser.parse_args(argv)

    report = backfill_traded_tickers(limit=args.limit)
    print(
        f"SIC backfill: {report.candidates} traded ticker(s) without an instrument; "
        f"{report.from_snapshot} via SEC snapshot, {report.matched_by_name} via exact name match "
        f"({report.new_instruments} new instrument(s), {report.ticker_map_only} added to an "
        f"existing CIK's instrument); {len(report.ambiguous)} ambiguous, "
        f"{report.unmatched} unmatched, {report.no_name} without a usable name."
    )

    synced = 0
    for _ in range(MAX_SIC_SYNC_ROUNDS):
        touched = sync_sic_codes()
        synced += touched
        if touched == 0:
            break
    print(f"SIC code sync: {synced} instrument(s) synced.")

    if report.aborted:
        raise SystemExit(f"Name lookups stopped early: {report.aborted}")


if __name__ == "__main__":
    main()
