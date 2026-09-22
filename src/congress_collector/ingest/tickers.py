"""Link transactions.instrument_id via the vendored SEC ticker/company
reference (T14).

For each transaction without an instrument yet: `data/ticker_overrides.csv`
is checked first (exact match on ticker or, failing that, on the full raw
description), then an exact lookup of the parser-extracted `ticker`
against SEC's list, then a fuzzy match of `asset_description_raw` against
SEC company names. `instruments`/`ticker_map` rows are created on demand,
one per distinct CIK/ticker actually seen -- this table isn't meant to
mirror SEC's full ~10k-company universe, only the securities we actually
observe in filings. Unresolved transactions get a dq_issues row, deduped
per T13's lesson (link_pending_filings) so a transaction that can never
match (a municipal bond, a private placement) doesn't get re-flagged every
5-minute run forever.

Point-in-time ticker changes aren't tracked yet: company_tickers.json is
SEC's current-day snapshot with no history, so `ticker_map.valid_from` is
just pinned to a fixed backfill-era date and `valid_to` left open. A
transaction whose ticker has since changed (a rename, not merely a new
listing) will fail to match today's SEC snapshot and land in the review
queue rather than being silently mislinked -- acceptable for now, and
revisited if/when a historical ticker-change source is added.
"""

import csv
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from congress_collector.db.models import DqIssue, Instrument, TickerMap, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.ticker_match import (
    match_by_description,
    match_by_ticker,
    normalize_ticker,
)
from congress_collector.sources.sec_tickers import SecCompany, load_sec_tickers

OVERRIDES_PATH = Path(__file__).resolve().parents[3] / "data" / "ticker_overrides.csv"
BATCH_SIZE = 1000

# SEC data has no ticker-change history, so every instrument this step
# creates gets the same fixed validity start -- the earliest date the
# plan's furthest-back backfill period (T20/T21) reaches.
DEFAULT_VALID_FROM = date(2012, 1, 1)


@dataclass(frozen=True)
class Override:
    ticker: str | None
    cik: str | None
    reason: str


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[tuple[str, str], Override]:
    overrides: dict[tuple[str, str], Override] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            key = (row["match_type"].strip(), row["match_value"].strip())
            overrides[key] = Override(
                ticker=row["ticker"].strip() or None,
                cik=row["cik"].strip() or None,
                reason=row["reason"].strip(),
            )
    return overrides


def count_pending() -> int:
    """How many transactions still don't have an instrument_id. Used by
    the catch-up backlog drain -- link_pending_transactions()'s return
    value alone (successful links only) can't tell "nothing left pending"
    apart from "a batch's candidates were all already-flagged unmatched
    ones"."""
    with session_scope() as session:
        count = session.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.instrument_id.is_(None))
        )
        return count or 0


def link_pending_transactions(*, batch_size: int = BATCH_SIZE) -> int:
    """Assign instrument_id to up to `batch_size` transactions that don't
    have one yet. Returns the number successfully linked."""
    companies = load_sec_tickers()
    by_ticker = {c.ticker: c for c in companies}
    overrides = load_overrides()

    linked = 0
    with session_scope() as session:
        already_flagged = _already_flagged_transaction_ids(session)
        instrument_by_cik = _existing_instruments_by_cik(session)
        ticker_map_keys = _existing_ticker_map_keys(session)

        # Never-yet-flagged transactions first -- see
        # politician_links.link_pending_filings's matching note (confirmed
        # live here too: 3,405/19,897 transactions linked, with 1,206
        # already-flagged-unmatched transactions exceeding this step's own
        # batch_size, so every run was re-selecting the same stuck rows).
        already_flagged_ids = select(DqIssue.transaction_id).where(
            DqIssue.issue_type == "ticker_match_unmatched", DqIssue.resolved_at.is_(None)
        )
        priority = case((Transaction.transaction_id.in_(already_flagged_ids), 1), else_=0)
        pending = session.scalars(
            select(Transaction)
            .where(Transaction.instrument_id.is_(None))
            .order_by(priority)
            .limit(batch_size)
        ).all()

        for tx in pending:
            company = _resolve(tx, overrides, by_ticker, companies)
            if company is None:
                if tx.transaction_id not in already_flagged:
                    session.add(
                        DqIssue(
                            filing_id=tx.filing_id,
                            transaction_id=tx.transaction_id,
                            issue_type="ticker_match_unmatched",
                            details=(
                                f"ticker={tx.ticker!r} description={tx.asset_description_raw!r}"
                            ),
                        )
                    )
                    already_flagged.add(tx.transaction_id)
                continue

            instrument_id = instrument_by_cik.get(company.cik)
            if instrument_id is None:
                instrument_id = uuid.uuid4()
                session.add(
                    Instrument(
                        instrument_id=instrument_id,
                        primary_ticker=company.ticker,
                        cik=company.cik,
                        name=company.title,
                        asset_class="equity",
                    )
                )
                instrument_by_cik[company.cik] = instrument_id

            if (instrument_id, company.ticker) not in ticker_map_keys:
                session.add(
                    TickerMap(
                        ticker_map_id=uuid.uuid4(),
                        instrument_id=instrument_id,
                        ticker=company.ticker,
                        valid_from=DEFAULT_VALID_FROM,
                        valid_to=None,
                        source="sec",
                    )
                )
                ticker_map_keys.add((instrument_id, company.ticker))

            tx.instrument_id = instrument_id
            if tx.ticker is None:
                tx.ticker = company.ticker
            linked += 1
    return linked


def _resolve(
    tx: Transaction,
    overrides: dict[tuple[str, str], Override],
    by_ticker: dict[str, SecCompany],
    companies: list[SecCompany],
) -> SecCompany | None:
    if tx.ticker:
        override = overrides.get(("ticker", normalize_ticker(tx.ticker)))
        if override is not None:
            return _company_from_override(override, by_ticker)

        company = match_by_ticker(tx.ticker, by_ticker)
        if company is not None:
            return company

    override = overrides.get(("description", tx.asset_description_raw.strip()))
    if override is not None:
        return _company_from_override(override, by_ticker)

    return match_by_description(tx.asset_description_raw, companies).company


def _company_from_override(
    override: Override, by_ticker: dict[str, SecCompany]
) -> SecCompany | None:
    if override.ticker is None:
        return None
    existing = by_ticker.get(normalize_ticker(override.ticker))
    if existing is not None:
        return existing
    # An override for a ticker SEC's snapshot doesn't (or no longer) list.
    return SecCompany(
        cik=(override.cik or "").zfill(10),
        ticker=normalize_ticker(override.ticker),
        title=override.reason,
    )


def _already_flagged_transaction_ids(session: Session) -> set[uuid.UUID]:
    ids = session.scalars(
        select(DqIssue.transaction_id).where(
            DqIssue.issue_type == "ticker_match_unmatched",
            DqIssue.resolved_at.is_(None),
        )
    )
    return {i for i in ids if i is not None}


def _existing_instruments_by_cik(session: Session) -> dict[str, uuid.UUID]:
    rows = session.execute(
        select(Instrument.cik, Instrument.instrument_id).where(Instrument.cik.is_not(None))
    ).all()
    return {cik: instrument_id for cik, instrument_id in rows if cik is not None}


def _existing_ticker_map_keys(session: Session) -> set[tuple[uuid.UUID, str]]:
    rows = session.execute(select(TickerMap.instrument_id, TickerMap.ticker)).all()
    return {(instrument_id, ticker) for instrument_id, ticker in rows}


def main() -> None:
    linked = link_pending_transactions()
    print(f"Ticker linking: {linked} transaction(s) linked.")


if __name__ == "__main__":
    main()
