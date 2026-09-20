"""Classify archived House PTR PDFs as electronic/scanned, and parse the
electronic ones into `transactions` rows.

Reads the PDF back from the `congress-raw` bucket (T7's archive) rather
than re-fetching it from the House site, since the raw archive is meant
to be the thing everything downstream re-derives from.
"""

from datetime import date

from sqlalchemy import select

from congress_collector.db.models import DqIssue, Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download

BATCH_SIZE = 25


def parse_pending_house_ptrs(*, batch_size: int = BATCH_SIZE) -> int:
    """Classify+parse up to `batch_size` archived House PTR filings that
    haven't been classified yet. Returns the number successfully parsed."""
    pending = _fetch_pending(batch_size)
    parsed_count = 0
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
        parsed_count += 1
    return parsed_count


def main() -> None:
    parsed = parse_pending_house_ptrs()
    print(f"House PTR parse: {parsed} filing(s) parsed.")


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
                    tx_type=t.tx_type,
                    tx_date=_parse_iso_date(t.tx_date),
                    notification_date=_parse_iso_date(t.notification_date),
                    amount_min=t.amount_min,
                    amount_max=t.amount_max,
                )
            )


def _parse_iso_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


if __name__ == "__main__":
    main()
