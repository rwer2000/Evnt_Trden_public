"""Fetch archived-but-unparsed Senate PTR pages, archive the raw HTML,
and parse the electronic ones into `transactions` rows.

Paper filings are already marked `parse_status = 'paper_deferred'` at
detection time (T9), since the search result link path alone says
paper vs. electronic -- this module only ever sees electronic ones.
"""

from sqlalchemy import select

from congress_collector.db.models import DqIssue, Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.senate_ptr import ParsedTransaction, parse_ptr_html
from congress_collector.sources.senate import new_session
from congress_collector.storage.supabase_storage import sha256_hex, upload

BATCH_SIZE = 25


def parse_pending_senate_ptrs(*, batch_size: int = BATCH_SIZE) -> int:
    """Fetch+archive+parse up to `batch_size` electronic Senate PTRs that
    haven't been parsed yet. Returns the number successfully parsed."""
    pending = _fetch_pending(batch_size)
    if not pending:
        return 0

    session = new_session()
    parsed_count = 0
    for filing_id, report_uuid in pending:
        url = f"https://efdsearch.senate.gov/search/view/ptr/{report_uuid}/"
        response = session.get(url)
        if response.status_code != 200:
            _mark_failed(filing_id, f"GET {url} -> {response.status_code}")
            continue

        html = response.text
        transactions = parse_ptr_html(html)
        if not transactions:
            _mark_failed(filing_id, "no transactions parsed from an electronic PTR")
            continue

        object_key = f"senate/{report_uuid}.html"
        upload(object_key, html.encode("utf-8"), "text/html")
        _save_transactions(filing_id, object_key, html, transactions)
        parsed_count += 1
    return parsed_count


def main() -> None:
    parsed = parse_pending_senate_ptrs()
    print(f"Senate PTR parse: {parsed} filing(s) parsed.")


def _fetch_pending(limit: int) -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id)
            .where(
                Filing.chamber == "senate",
                Filing.filing_type == "P",
                Filing.format == "electronic",
                Filing.parse_status == "pending",
            )
            .limit(limit)
        ).all()
        return [(filing_id, filing_id.removeprefix("senate:")) for (filing_id,) in rows]


def _mark_failed(filing_id: str, detail: str) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is not None:
            filing.parse_status = "failed"
        session.add(DqIssue(filing_id=filing_id, issue_type="ptr_parse_failed", details=detail))


def _save_transactions(
    filing_id: str, object_key: str, html: str, transactions: list[ParsedTransaction]
) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None:
            return
        filing.parse_status = "parsed"
        filing.raw_object_key = object_key
        filing.raw_sha256 = sha256_hex(html.encode("utf-8"))

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
                    expiry=t.expiry,
                    tx_type=t.tx_type,
                    tx_date=t.tx_date,
                    notification_date=None,
                    amount_min=t.amount_min,
                    amount_max=t.amount_max,
                )
            )


if __name__ == "__main__":
    main()
