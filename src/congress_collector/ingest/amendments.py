"""Link House PTR amendments to the transaction they correct, and keep
`transactions.is_current` accurate (T16).

The House PTR form's per-row "ID" column (`source_transaction_id`) is a
persistent identifier that stays the same across an original filing and
any later filing that amends that specific transaction -- confirmed live
against a real "Filing Status: Amended" row (see `parsers.house_ptr`).
Senate has no equivalent signal, so this only ever touches House rows;
`source_transaction_id` stays NULL for Senate transactions and they're
excluded by construction.

Whenever the same `source_transaction_id` shows up on transactions from
more than one filing, only the one from the most-recently-filed filing
counts as current (the plan's own wording: "only the most recent
counts") -- the rest get `is_current = false`, still in the table for
audit/history. The amendment's filing also gets `supersedes_filing_id`
pointed at the earliest filing in the group, best-effort (only filled in
if not already set).

This is a small, self-limiting scan (grouped by `source_transaction_id`
with more than one distinct filing, not a per-row batch), so unlike
`politician_links`/`tickers` it doesn't need an explicit batch size or a
dedup guard: a group already resolved to the right `is_current` values is
a cheap no-op read on every subsequent run, not a repeated write.
"""

from datetime import date, datetime

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from congress_collector.db.models import Filing, Transaction
from congress_collector.db.session import session_scope


def link_amendments() -> int:
    """Update is_current (and supersedes_filing_id, best-effort) for every
    source_transaction_id shared across more than one filing. Returns the
    number of transaction rows whose is_current actually changed."""
    updated = 0
    with session_scope() as session:
        for source_id in _amended_source_ids(session):
            updated += _resolve_group(session, source_id)
    return updated


def _amended_source_ids(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(Transaction.source_transaction_id)
            .where(Transaction.source_transaction_id.is_not(None))
            .group_by(Transaction.source_transaction_id)
            .having(func.count(func.distinct(Transaction.filing_id)) > 1)
        )
    )


def _resolve_group(session: Session, source_id: str) -> int:
    rows = session.execute(
        select(Transaction, Filing.filed_date, Filing.first_seen_at, Filing.filing_id)
        .join(Filing, Filing.filing_id == Transaction.filing_id)
        .where(Transaction.source_transaction_id == source_id)
    ).all()
    if len(rows) < 2:
        return 0

    def sort_key(row: Row[tuple[Transaction, date | None, datetime, str]]) -> tuple[date, datetime]:
        _, filed_date, first_seen_at, _ = row
        return (filed_date or date.min, first_seen_at)

    ordered = sorted(rows, key=sort_key)
    newest_tx = ordered[-1][0]
    newest_filing_id = ordered[-1][3]
    oldest_filing_id = ordered[0][3]

    updated = 0
    for tx, _filed_date, _first_seen_at, _filing_id in rows:
        should_be_current = tx is newest_tx
        if tx.is_current != should_be_current:
            tx.is_current = should_be_current
            updated += 1

    if newest_filing_id != oldest_filing_id:
        newest_filing = session.get(Filing, newest_filing_id)
        if newest_filing is not None and newest_filing.supersedes_filing_id is None:
            newest_filing.supersedes_filing_id = oldest_filing_id

    return updated


def main() -> None:
    updated = link_amendments()
    print(f"Amendment linking: {updated} transaction(s) updated.")


if __name__ == "__main__":
    main()
