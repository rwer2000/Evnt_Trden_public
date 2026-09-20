"""Backfill option_type/strike/expiry for House PTR transactions parsed
before T15 added option-detail extraction.

Not part of the regular collect.yml pipeline: filings only ever get
parsed once (parse_pending_house_ptrs only looks at format = 'unknown'),
so a parser improvement like T15's never reaches already-parsed filings
on its own. Run manually
(`uv run python -m congress_collector.ingest.backfill_house_options`)
after a parser change like this one. Safe to re-run -- it only touches
asset_type = 'OP' rows with option_type still NULL, so it's a no-op once
caught up.
"""

from datetime import date

from sqlalchemy import select

from congress_collector.db.models import Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download


def backfill_option_details() -> int:
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
            .where(
                Filing.chamber == "house",
                Transaction.asset_type == "OP",
                Transaction.option_type.is_(None),
                Filing.raw_object_key.is_not(None),
            )
            .distinct()
        ).all()
        return [(filing_id, object_key) for filing_id, object_key in rows if object_key]


def _apply(filing_id: str, parsed_by_row: dict[int, ParsedTransaction]) -> int:
    updated = 0
    with session_scope() as session:
        pending = session.scalars(
            select(Transaction).where(
                Transaction.filing_id == filing_id,
                Transaction.asset_type == "OP",
                Transaction.option_type.is_(None),
            )
        ).all()
        for tx in pending:
            parsed = parsed_by_row.get(tx.row_index)
            if parsed is None or parsed.option_type is None:
                continue
            tx.option_type = parsed.option_type
            tx.strike = parsed.strike
            tx.expiry = date.fromisoformat(parsed.expiry) if parsed.expiry else None
            updated += 1
    return updated


def main() -> None:
    updated = backfill_option_details()
    print(f"Backfilled option details for {updated} transaction(s).")


if __name__ == "__main__":
    main()
