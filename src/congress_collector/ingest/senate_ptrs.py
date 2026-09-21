"""Fetch archived-but-unparsed Senate PTR pages, archive the raw HTML,
and parse the electronic ones into `transactions` rows.

Paper filings are already marked `parse_status = 'paper_deferred'` at
detection time (T9), since the search result link path alone says
paper vs. electronic -- this module only ever sees electronic ones.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from congress_collector.db.models import (
    Committee,
    CommitteeMembership,
    DqIssue,
    Filing,
    Politician,
    Transaction,
)
from congress_collector.db.session import session_scope
from congress_collector.ingest.senate import DEFAULT_PRECISION_S
from congress_collector.notify.telegram import send_message
from congress_collector.parsers.senate_ptr import ParsedTransaction, parse_ptr_html
from congress_collector.sources.senate import new_session, ptr_url_for
from congress_collector.storage.supabase_storage import sha256_hex, upload

BATCH_SIZE = 25

# Cap on how many transaction lines a single parsed-transactions Telegram
# message lists -- see house_ptrs.NOTIFY_MAX_LINES's matching note.
NOTIFY_MAX_LINES = 15

# Cap on how many committee names a filer's description lists (T23) -- see
# house_ptrs.MAX_COMMITTEES_SHOWN's matching note.
MAX_COMMITTEES_SHOWN = 3

_TX_LABELS = {
    "purchase": "BUY",
    "sale_full": "SELL",
    "sale_partial": "SELL (partial)",
    "exchange": "EXCHANGE",
}


def parse_pending_senate_ptrs(*, batch_size: int = BATCH_SIZE) -> list[str]:
    """Fetch+archive+parse up to `batch_size` electronic Senate PTRs that
    haven't been parsed yet. Returns the filing_ids that were successfully
    parsed into transactions."""
    pending = _fetch_pending(batch_size)
    if not pending:
        return []

    session = new_session()
    parsed_filing_ids = []
    for filing_id, report_uuid in pending:
        url = ptr_url_for(report_uuid)
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
        parsed_filing_ids.append(filing_id)
    return parsed_filing_ids


def main() -> None:
    parsed_filing_ids = parse_pending_senate_ptrs()
    print(f"Senate PTR parse: {len(parsed_filing_ids)} filing(s) parsed.")
    if parsed_filing_ids:
        notify_parsed_transactions(parsed_filing_ids)


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


def notify_parsed_transactions(filing_ids: Sequence[str]) -> None:
    """Send a Telegram message detailing the transactions just parsed for
    `filing_ids`, restricted to filings detected live (first_seen_precision_s
    == DEFAULT_PRECISION_S) -- see house_ptrs.notify_parsed_transactions's
    matching note on why (T20's backfill shares this same pending queue)."""
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
            committees = _committee_labels(session, politician)
            who = describe_filer(filing.filer_name, politician, committees)
            url = ptr_url_for(filing.filing_id.removeprefix("senate:"))
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
                lines.append(f"{who}: {describe_transaction(t)} — {url}")

    if not lines:
        return
    remaining = len(lines) - NOTIFY_MAX_LINES
    shown = lines[:NOTIFY_MAX_LINES]
    if remaining > 0:
        shown.append(f"...and {remaining} more transaction(s)")
    text = f"Senate: {len(lines)} transaction(s) parsed\n" + "\n".join(shown)
    try:
        send_message(text, category="filing")
    except Exception as exc:
        # Best-effort: a Telegram outage must never break ingestion, the
        # one thing this function absolutely cannot fail to do.
        print(f"Failed to send parsed-transaction notification: {exc}")


def _committee_labels(session: Session, politician: Politician | None) -> list[str]:
    """Committee names (T23) a politician sits on, each with its title
    (e.g. "Chairman") appended when the membership row carries one."""
    if politician is None:
        return []
    rows = session.execute(
        select(Committee.name, CommitteeMembership.title)
        .join(CommitteeMembership, CommitteeMembership.thomas_id == Committee.thomas_id)
        .where(CommitteeMembership.bioguide_id == politician.bioguide_id)
        .order_by(Committee.name)
    ).all()
    return [f"{name} ({title})" if title else name for name, title in rows]


def describe_filer(
    filer_name: str, politician: Politician | None, committees: Sequence[str] = ()
) -> str:
    if politician is None:
        return filer_name
    party_state = "-".join(p for p in (politician.party, politician.state) if p)
    who = f"{politician.full_name} ({party_state})" if party_state else politician.full_name
    if committees:
        shown = list(committees[:MAX_COMMITTEES_SHOWN])
        if len(committees) > MAX_COMMITTEES_SHOWN:
            shown.append(f"+{len(committees) - MAX_COMMITTEES_SHOWN} more")
        who += f" [{', '.join(shown)}]"
    return who


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
