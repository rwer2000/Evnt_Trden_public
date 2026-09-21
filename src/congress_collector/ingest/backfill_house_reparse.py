"""Re-parse already-parsed House PTR filings to backfill fields a parser
change added -- or a parser bug fix corrected -- after they were first
parsed: option_type/strike/expiry (T15), source_transaction_id (T16),
and asset_type for tickerless rows like government securities and
private holdings (T17), and whatever the next one turns out to be.

Not part of the regular collect.yml pipeline: filings only ever get
parsed once (parse_pending_house_ptrs only looks at format = 'unknown'),
so a parser improvement never reaches already-parsed filings on its own.
Run manually (`uv run python -m
congress_collector.ingest.backfill_house_reparse`) after a parser change
like T15's or T16's. Safe to re-run -- it only touches transactions still
missing one of the backfilled fields, so it's a no-op once caught up.
"""

from datetime import date

from sqlalchemy import or_, select

from congress_collector.db.models import Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download

# A transaction needs re-parsing if any backfilled field it's eligible
# for is still missing.
_NEEDS_BACKFILL = or_(
    Transaction.source_transaction_id.is_(None),
    (Transaction.asset_type == "OP") & Transaction.option_type.is_(None),
    Transaction.asset_type.is_(None),
)


def backfill_missing_fields() -> int:
    updated = 0
    for filing_id, object_key in _filings_needing_backfill():
        content = download(object_key)
        parsed_by_row = {
            t.row_index: t for t in parse_ptr_transactions(extract_pages_words(content))
        }
        updated += _apply(filing_id, parsed_by_row)
    return updated


def _filings_needing_backfill() -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key)
            .join(Transaction, Transaction.filing_id == Filing.filing_id)
            .where(Filing.chamber == "house", _NEEDS_BACKFILL, Filing.raw_object_key.is_not(None))
            .distinct()
        ).all()
        return [(filing_id, object_key) for filing_id, object_key in rows if object_key]


def _apply(filing_id: str, parsed_by_row: dict[int, ParsedTransaction]) -> int:
    updated = 0
    with session_scope() as session:
        pending = session.scalars(
            select(Transaction).where(Transaction.filing_id == filing_id, _NEEDS_BACKFILL)
        ).all()
        for tx in pending:
            parsed = parsed_by_row.get(tx.row_index)
            if parsed is None:
                continue
            changed = False

            if tx.source_transaction_id is None and parsed.source_transaction_id is not None:
                tx.source_transaction_id = parsed.source_transaction_id
                changed = True

            if tx.asset_type is None and parsed.asset_type is not None:
                tx.asset_type = parsed.asset_type
                changed = True

            if tx.asset_type == "OP" and tx.option_type is None and parsed.option_type is not None:
                tx.option_type = parsed.option_type
                tx.strike = parsed.strike
                tx.expiry = date.fromisoformat(parsed.expiry) if parsed.expiry else None
                changed = True

            if changed:
                updated += 1
    return updated


def main() -> None:
    updated = backfill_missing_fields()
    print(f"Backfilled {updated} transaction(s).")


if __name__ == "__main__":
    main()
