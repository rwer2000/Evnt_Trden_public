"""Parse archived House annual Financial Disclosure reports (FilingType 'O')
into `holdings` (Schedule A), so a member's portfolio can start from what
they already held rather than from their first PTR.

Same shape as `ingest.house_ptrs`: every run takes a batch of archived
reports still `format = 'unknown'` and leaves each one classified, whatever
the outcome, so the backlog drains and nothing is retried forever:

- no text layer at all: a scanned paper report, `format = 'scanned'`,
  `parse_status = 'paper_deferred'` (left for a later OCR/vision pass);
- a text layer with a Schedule A heading: `parsed`, with its holdings --
  possibly none, for a report whose Schedule A reads "None disclosed.";
- a text layer without one: `failed`, with a dq_issues row.

No Telegram notification: an annual report is history, not a signal.
"""

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError

from congress_collector.db.models import DqIssue, Filing, Holding
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_fd import (
    ParsedHolding,
    has_schedule_a,
    parse_schedule_a,
    report_year,
)
from congress_collector.parsers.house_ptr import extract_pages_words
from congress_collector.storage.r2_storage import download

BATCH_SIZE = 25
ISSUE_TYPE = "fd_parse_failed"


def parse_pending_house_fds(*, batch_size: int = BATCH_SIZE) -> tuple[int, int, int]:
    """Classify+parse up to `batch_size` archived annual reports.
    Returns (reports parsed, holdings saved, reports deferred or failed)."""
    parsed = holdings_saved = other = 0
    for filing_id, object_key in _fetch_pending(batch_size):
        try:
            pages_words = extract_pages_words(download(object_key))
        except Exception as exc:
            _mark_failed(filing_id, f"download/extract failed: {exc}")
            other += 1
            continue

        if not any(pages_words):
            _mark_paper_deferred(filing_id)
            other += 1
            continue
        if not has_schedule_a(pages_words):
            _mark_failed(filing_id, "text layer but no Schedule A heading")
            other += 1
            continue

        holdings = parse_schedule_a(pages_words)
        try:
            _save_holdings(filing_id, report_year(pages_words), holdings)
        except IntegrityError:
            continue  # a concurrent run already stored this report
        parsed += 1
        holdings_saved += len(holdings)
    return parsed, holdings_saved, other


def count_pending() -> int:
    with session_scope() as session:
        return (
            session.scalar(select(func.count()).select_from(Filing).where(*_pending_filter())) or 0
        )


def main() -> None:
    parsed, holdings, other = parse_pending_house_fds()
    print(
        f"House annual reports: {parsed} parsed ({holdings} holdings), "
        f"{other} deferred/failed, {count_pending()} still pending."
    )


def _pending_filter() -> tuple[ColumnElement[bool], ...]:
    return (
        Filing.chamber == "house",
        Filing.filing_type == "O",
        Filing.format == "unknown",
        Filing.raw_object_key.is_not(None),
    )


def _fetch_pending(limit: int) -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key)
            .where(*_pending_filter())
            .order_by(Filing.filed_date.desc())
            .limit(limit)
        ).all()
        return [(filing_id, key) for filing_id, key in rows if key]


def _save_holdings(filing_id: str, year: int | None, holdings: list[ParsedHolding]) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None:
            return
        filing.format = "electronic"
        filing.parse_status = "parsed"
        for h in holdings:
            session.add(
                Holding(
                    filing_id=filing_id,
                    row_index=h.row_index,
                    report_year=year,
                    owner=h.owner,
                    asset_description_raw=h.asset_description_raw,
                    ticker=h.ticker,
                    asset_type=h.asset_type,
                    value_raw=h.value_raw,
                    value_min=h.value_min,
                    value_max=h.value_max,
                    income_type=h.income_type,
                    income_raw=h.income_raw,
                )
            )


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
        session.add(DqIssue(filing_id=filing_id, issue_type=ISSUE_TYPE, details=detail))


if __name__ == "__main__":
    main()
