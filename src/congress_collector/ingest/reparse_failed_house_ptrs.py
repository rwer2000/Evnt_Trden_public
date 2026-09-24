"""Re-parse House PTR filings previously marked `parse_status = 'failed'`
(zero transactions extracted), now that the parser handles several
pre-2022 House form quirks that used to defeat it entirely -- see
`parsers/house_ptr.py`'s module docstring for the full list. At the time
this script was written those quirks caused a 100% parse-failure rate for
every House PTR filed 2015 through most of 2021.

Not part of the regular collect.yml pipeline: `parse_pending_house_ptrs`
only ever looks at `format = 'unknown'` filings and never retries a
`failed` one on its own, so a parser fix expected to newly parse
previously-failed filings needs this separate, manually-run pass. Run
manually (`uv run python -m
congress_collector.ingest.reparse_failed_house_ptrs`) after a parser fix
like that one. Safe to re-run -- a filing that still doesn't parse is left
exactly as it was (`parse_status` stays `'failed'`, its `dq_issues` row
stays unresolved).
"""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from congress_collector.db.models import DqIssue, Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download

ISSUE_TYPE = "ptr_parse_failed"


def reparse_failed_filings() -> tuple[int, int]:
    """Returns (filings newly parsed, filings still failing)."""
    now_parsed = 0
    still_failed = 0
    for filing_id, object_key in _failed_filings():
        try:
            content = download(object_key)
            pages_words = extract_pages_words(content)
        except Exception:
            still_failed += 1
            continue

        transactions = parse_ptr_transactions(pages_words)
        if not transactions:
            still_failed += 1
            continue

        try:
            _save_and_resolve(filing_id, transactions)
        except IntegrityError:
            # Another process (e.g. a concurrently-running catch-up run)
            # already parsed this filing -- nothing left to do here.
            continue
        now_parsed += 1
    return now_parsed, still_failed


def _failed_filings() -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key).where(
                Filing.chamber == "house",
                Filing.filing_type == "P",
                Filing.parse_status == "failed",
                Filing.raw_object_key.is_not(None),
            )
        ).all()
        return [(filing_id, object_key) for filing_id, object_key in rows if object_key]


def _save_and_resolve(filing_id: str, transactions: list[ParsedTransaction]) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None:
            return
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

        unresolved_issues = session.scalars(
            select(DqIssue).where(
                DqIssue.filing_id == filing_id,
                DqIssue.issue_type == ISSUE_TYPE,
                DqIssue.resolved_at.is_(None),
            )
        ).all()
        for issue in unresolved_issues:
            issue.resolved_at = datetime.now(UTC)


def _parse_iso_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    now_parsed, still_failed = reparse_failed_filings()
    print(f"House PTR re-parse: {now_parsed} filing(s) newly parsed, {still_failed} still failed.")


if __name__ == "__main__":
    main()
