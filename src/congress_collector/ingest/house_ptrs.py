"""Classify archived House PTR PDFs as electronic/scanned, and parse the
electronic ones into `transactions` rows.

Reads the PDF back from the `congress-raw` bucket (T7's archive) rather
than re-fetching it from the House site, since the raw archive is meant
to be the thing everything downstream re-derives from.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
from congress_collector.ingest.house import DEFAULT_PRECISION_S
from congress_collector.notify.telegram import send_message
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.sources.house import pdf_url_for
from congress_collector.storage.supabase_storage import download

BATCH_SIZE = 25

# Cap on how many transaction lines a single parsed-transactions Telegram
# message lists -- see house.NOTIFY_MAX_LINES's matching note.
NOTIFY_MAX_LINES = 15

# Cap on how many committee names a filer's description lists (T23) --
# some members sit on several; the point is a quick "who is this and what
# do they oversee" glance, not an exhaustive roster.
MAX_COMMITTEES_SHOWN = 3

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
        # A transient Storage read failure here used to crash the whole
        # process -- confirmed live: house_pdfs.py's matching upload()
        # call did the same thing on a long catch-up run. Treated the
        # same way "no transactions parsed" already was: marked failed
        # (removes it from `format = 'unknown'` pending either way) with
        # a dq_issues row, rather than losing the rest of the batch.
        try:
            content = download(object_key)
            pages_words = extract_pages_words(content)
        except Exception as exc:
            _mark_failed(filing_id, f"download/extract failed: {exc}")
            continue

        if not is_electronic(pages_words):
            _mark_paper_deferred(filing_id)
            continue

        transactions = parse_ptr_transactions(pages_words)
        if not transactions:
            _mark_failed(filing_id, "no transactions parsed from an electronic PTR")
            continue

        # _fetch_pending() doesn't claim rows, so this filing can also be
        # mid-parse in a concurrently-running process -- confirmed live: a
        # regular collect.yml run and a manually-triggered
        # catchup_house_backlog.py run both selected the same filing and
        # both tried to insert the same (filing_id, row_index) transaction
        # rows, crashing whichever one lost the race with a raw
        # IntegrityError. The other process's insert already recorded
        # this filing as parsed, so there's nothing left for us to do.
        try:
            _save_transactions(filing_id, transactions)
        except IntegrityError:
            continue
        parsed_filing_ids.append(filing_id)
    return parsed_filing_ids


def main() -> None:
    parsed_filing_ids = parse_pending_house_ptrs()
    print(f"House PTR parse: {len(parsed_filing_ids)} filing(s) parsed.")
    if parsed_filing_ids:
        notify_parsed_transactions(parsed_filing_ids)


def count_pending() -> int:
    """How many archived House PTRs still haven't been classified/parsed.
    Used by the catch-up backlog drain -- every row this step touches
    leaves `format = 'unknown'` regardless of outcome (parsed, paper, or
    failed), so unlike the archive/link stages there's no "stuck forever"
    risk here, but the count is still the correct stopping signal: a
    batch that's all paper/failed returns 0 from
    parse_pending_house_ptrs() even though real progress happened."""
    with session_scope() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Filing)
            .where(
                Filing.chamber == "house",
                Filing.filing_type == "P",
                Filing.format == "unknown",
                Filing.raw_object_key.is_not(None),
            )
        )
        return count or 0


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
            committees = _committee_labels(session, politician)
            who = describe_filer(filing.filer_name, politician, committees)
            year = filing.filed_date.year if filing.filed_date else datetime.now(UTC).year
            url = pdf_url_for(filing.filing_id.removeprefix("house:"), filing.filing_type, year)
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
    text = f"House: {len(lines)} transaction(s) parsed\n" + "\n".join(shown)
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
