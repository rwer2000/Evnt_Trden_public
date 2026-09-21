"""Classify archived House PTR PDFs as electronic/scanned, and parse the
electronic ones into `transactions` rows.

Reads the PDF back from the `congress-raw` bucket (T7's archive) rather
than re-fetching it from the House site, since the raw archive is meant
to be the thing everything downstream re-derives from.
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select

from congress_collector.db.models import DqIssue, Filing, Politician, Transaction
from congress_collector.db.session import session_scope
from congress_collector.ingest.house import DEFAULT_PRECISION_S
from congress_collector.notify.telegram import send_message
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download

BATCH_SIZE = 25

# Cap on how many transaction lines a single parsed-transactions Telegram
# message lists -- see house.NOTIFY_MAX_LINES's matching note.
NOTIFY_MAX_LINES = 15

_TX_LABELS = {
    "purchase": "BUY",
    "sale_full": "SELL",
    "sale_partial": "SELL (partial)",
    "exchange": "EXCHANGE",
}


def parse_pending_house_ptrs(*, batch_size: int = BATCH_SIZE) -> list[str]:
    """Classify+parse up to `batch_size` archived House PTR filings that
    haven't been classified yet. Returns the filing_ids that were
    successfully parsed into transactions (excludes ones deferred as
    paper/scanned or that failed to parse)."""
    pending = _fetch_pending(batch_size)
    parsed_filing_ids = []
    for filing_id, object_key in pending:
        content = download(object_key)
        pages_words = extract_pages_words(content)

        if not is_electronic(pages_words):
            _mark_paper_deferred(filing_id)
            continue

        transactions = parse_ptr_transactions(pages_words)
        if not transactions:
            _mark_failed(filing_id, "no transactions parsed from an electronic PTR")
            continue

        _save_transactions(filing_id, transactions)
        parsed_filing_ids.append(filing_id)
    return parsed_filing_ids


def main() -> None:
    parsed_filing_ids = parse_pending_house_ptrs()
    print(f"House PTR parse: {len(parsed_filing_ids)} filing(s) parsed.")
    if parsed_filing_ids:
        notify_parsed_transactions(parsed_filing_ids)


def _fetch_pending(limit: int) -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key)
            .where(
                Filing.chamber == "house",
                Filing.filing_type == "P",
                Filing.format == "unknown",
                Filing.raw_object_key.is_not(None),
            )
            .limit(limit)
        ).all()
        return [(filing_id, object_key) for filing_id, object_key in rows if object_key]


def _mark_paper_deferred(filing_id: str) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is not None:
            filing.format = "scanned"
            filing.parse_status = "paper_deferred"


def _mark_failed(filing_id: str, detail: str) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is not None:
            filing.format = "electronic"
            filing.parse_status = "failed"
        session.add(DqIssue(filing_id=filing_id, issue_type="ptr_parse_failed", details=detail))


def _save_transactions(filing_id: str, transactions: list[ParsedTransaction]) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None:
            return
        filing.format = "electronic"
        filing.parse_status = "parsed"

        for t in transactions:
            if t.tx_type is None:
                session.add(
                    DqIssue(
                        filing_id=filing_id,
                        issue_type="unknown_tx_type",
                        details=f"row {t.row_index}: could not map to a known transaction type",
                    )
                )
                continue

            session.add(
                Transaction(
                    filing_id=filing_id,
                    row_index=t.row_index,
                    owner=t.owner,
                    asset_description_raw=t.asset_description_raw,
                    ticker=t.ticker,
                    asset_type=t.asset_type,
                    option_type=t.option_type,
                    strike=t.strike,
                    expiry=_parse_iso_date(t.expiry),
                    tx_type=t.tx_type,
                    tx_date=_parse_iso_date(t.tx_date),
                    notification_date=_parse_iso_date(t.notification_date),
                    amount_min=t.amount_min,
                    amount_max=t.amount_max,
                    source_transaction_id=t.source_transaction_id,
                )
            )


def _parse_iso_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def notify_parsed_transactions(filing_ids: Sequence[str]) -> None:
    """Send a Telegram message detailing the transactions just parsed for
    `filing_ids`, restricted to filings detected live (first_seen_precision_s
    == DEFAULT_PRECISION_S). This queue is shared with T20's backfill, which
    inserts filings with format='unknown' just like live sync does, so
    without this filter the backfill's ~46k historical House filings would
    flood the chat as this function's batches quietly work through them
    over time."""
    with session_scope() as session:
        filings = (
            session.execute(
                select(Filing)
                .where(
                    Filing.filing_id.in_(filing_ids),
                    Filing.first_seen_precision_s == DEFAULT_PRECISION_S,
                )
                .order_by(Filing.first_seen_at)
            )
            .scalars()
            .all()
        )
        if not filings:
            return

        lines = []
        for filing in filings:
            politician = session.get(Politician, filing.bioguide_id) if filing.bioguide_id else None
            who = describe_filer(filing.filer_name, politician)
            txs = (
                session.execute(
                    select(Transaction)
                    .where(Transaction.filing_id == filing.filing_id)
                    .order_by(Transaction.row_index)
                )
                .scalars()
                .all()
            )
            for t in txs:
                lines.append(f"{who}: {describe_transaction(t)}")

    if not lines:
        return
    remaining = len(lines) - NOTIFY_MAX_LINES
    shown = lines[:NOTIFY_MAX_LINES]
    if remaining > 0:
        shown.append(f"...and {remaining} more transaction(s)")
    text = f"House: {len(lines)} transaction(s) parsed\n" + "\n".join(shown)
    try:
        send_message(text, category="filing")
    except Exception as exc:
        # Best-effort: a Telegram outage must never break ingestion, the
        # one thing this function absolutely cannot fail to do.
        print(f"Failed to send parsed-transaction notification: {exc}")


def describe_filer(filer_name: str, politician: Politician | None) -> str:
    if politician is None:
        return filer_name
    party_state = "-".join(p for p in (politician.party, politician.state) if p)
    return f"{politician.full_name} ({party_state})" if party_state else politician.full_name


def describe_transaction(t: Transaction) -> str:
    label = _TX_LABELS.get(t.tx_type, t.tx_type)
    asset = t.ticker or t.asset_description_raw
    amount = _format_amount(t.amount_min, t.amount_max)
    owner = f" [{t.owner}]" if t.owner else ""
    return f"{label} {asset}{f' {amount}' if amount else ''}{owner}"


def _format_amount(amount_min: float | None, amount_max: float | None) -> str:
    if amount_min is None or amount_max is None:
        return ""
    return f"${amount_min:,.0f}-${amount_max:,.0f}"


if __name__ == "__main__":
    main()
