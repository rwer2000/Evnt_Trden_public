"""Download House Clerk PDFs for filings not yet archived, and store them
in Supabase Storage with a SHA-256 hash.

Classifying a filing as electronic/paper/scanned needs the PDF itself, so
that stays `format = 'unknown'` here and is T8's job.
"""

from datetime import UTC, date, datetime

import httpx
from sqlalchemy import case, func, select

from congress_collector.db.models import DqIssue, Filing
from congress_collector.db.session import session_scope
from congress_collector.sources.house import USER_AGENT, pdf_url_for
from congress_collector.storage.supabase_storage import sha256_hex, upload

BATCH_SIZE = 50

FETCH_FAILED_ISSUE_TYPE = "house_pdf_fetch_failed"


def archive_pending_house_pdfs(*, batch_size: int = BATCH_SIZE) -> int:
    """Download+archive PDFs for up to `batch_size` House filings that
    don't have one yet. Returns the number successfully archived; filings
    whose PDF couldn't be fetched are left pending, flagged with a
    dq_issues row so _fetch_pending() stops preferring them over filings
    that haven't been tried at all yet (see its docstring)."""
    pending = _fetch_pending(batch_size)
    archived = 0
    client = httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT})
    try:
        for filing_id, doc_id, filing_type, filed_date in pending:
            year = filed_date.year if filed_date else datetime.now(UTC).year
            url = pdf_url_for(doc_id, filing_type, year)
            try:
                response = client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                _record_fetch_failed(filing_id, f"GET {url} -> {exc}")
                continue

            content = response.content
            object_key = f"house/{year}/{doc_id}.pdf"
            upload(object_key, content, "application/pdf")
            _record_archived(filing_id, object_key, sha256_hex(content))
            archived += 1
    finally:
        client.close()
    return archived


def count_pending() -> int:
    """How many House filings still don't have a raw_object_key. Used by
    the catch-up backlog drain to tell "nothing left pending" apart from
    "a batch's PDF fetches all failed" -- archive_pending_house_pdfs()'s
    return value alone can't distinguish those two (see
    catchup_house_backlog.py's matching note)."""
    with session_scope() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Filing)
            .where(Filing.chamber == "house", Filing.raw_object_key.is_(None))
        )
        return count or 0


def main() -> None:
    archived = archive_pending_house_pdfs()
    print(f"House PDF archive: {archived} filing(s) archived.")


def _fetch_pending(limit: int) -> list[tuple[str, str, str, date | None]]:
    with session_scope() as session:
        # Two-tier priority, so a `LIMIT` batch can never get permanently
        # stuck on filings that will never archive:
        #
        # 1. Never-yet-failed first, PTRs (filing_type 'P') ahead of
        #    everything else within that tier. PTRs are the only type
        #    house_ptrs.py ever parses into transactions, but this table
        #    is dominated by other filing types (annual reports,
        #    amendments, extensions, ...) that sit archived and otherwise
        #    untouched forever -- confirmed live: 395/7,666 House PTRs
        #    archived weeks after T20's backfill landed, most of this
        #    step's budget spent on the ~40k non-PTR filings instead.
        # 2. Previously-failed (flagged via a dq_issues row below) last,
        #    regardless of type. Without this tier, a filing whose PDF
        #    404s permanently (an old filing no longer served, say) would
        #    otherwise keep winning tier 1's own PTR-first ordering and
        #    crowd out every filing that hasn't been tried at all --
        #    confirmed live: a catch-up run "completed" having archived
        #    only 3,226 of 7,666 PTRs, because it kept re-selecting the
        #    same batch of permanently-unfetchable filings and never
        #    reaching the untried remainder.
        already_failed = select(DqIssue.filing_id).where(
            DqIssue.issue_type == FETCH_FAILED_ISSUE_TYPE, DqIssue.resolved_at.is_(None)
        )
        failed_priority = case((Filing.filing_id.in_(already_failed), 1), else_=0)
        type_priority = case((Filing.filing_type == "P", 0), else_=1)
        rows = session.execute(
            select(Filing.filing_id, Filing.filing_type, Filing.filed_date)
            .where(Filing.chamber == "house", Filing.raw_object_key.is_(None))
            .order_by(failed_priority, type_priority)
            .limit(limit)
        ).all()
        return [
            (filing_id, filing_id.removeprefix("house:"), filing_type, filed_date)
            for filing_id, filing_type, filed_date in rows
        ]


def _record_archived(filing_id: str, object_key: str, sha256: str) -> None:
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is not None:
            filing.raw_object_key = object_key
            filing.raw_sha256 = sha256


def _record_fetch_failed(filing_id: str, detail: str) -> None:
    with session_scope() as session:
        already_flagged = session.scalar(
            select(DqIssue.issue_id).where(
                DqIssue.filing_id == filing_id,
                DqIssue.issue_type == FETCH_FAILED_ISSUE_TYPE,
                DqIssue.resolved_at.is_(None),
            )
        )
        if already_flagged is None:
            session.add(
                DqIssue(filing_id=filing_id, issue_type=FETCH_FAILED_ISSUE_TYPE, details=detail)
            )


if __name__ == "__main__":
    main()
