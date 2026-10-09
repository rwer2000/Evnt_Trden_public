"""Download House Clerk PDFs for filings not yet archived, and store them
in Cloudflare R2 with a SHA-256 hash.

Classifying a filing as electronic/paper/scanned needs the PDF itself, so
that stays `format = 'unknown'` here and is T8's job.
"""

from datetime import UTC, date, datetime

import httpx
from sqlalchemy import case, func, select

from congress_collector.db.models import DqIssue, Filing
from congress_collector.db.session import session_scope
from congress_collector.sources.house import USER_AGENT, pdf_url_for
from congress_collector.storage import quota
from congress_collector.storage.r2_storage import BUCKET, sha256_hex, upload

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
            filed_year = filed_date.year if filed_date else datetime.now(UTC).year
            # Covers the House-site fetch, the budget check, and the R2
            # upload -- confirmed live (back when this used Supabase
            # Storage) that a catch-up run crashed the whole process on an
            # httpx.ReadTimeout from upload() (a transient Storage-side
            # blip after tens of thousands of prior calls), since only the
            # fetch used to be wrapped. Every failure gets the same
            # treatment: flag and move on, not lose the run -- including
            # quota.StorageBudgetExceededError, which just means the archive
            # stays paused at its ceiling until reconcile()'s next run
            # confirms there's room again.
            try:
                year, content = _fetch_pdf(client, doc_id, filing_type, filed_year)
                object_key = f"house/{year}/{doc_id}.pdf"
                quota.ensure_budget(BUCKET, len(content))
                upload(object_key, content, "application/pdf")
                quota.record_bytes(BUCKET, len(content))
            except Exception as exc:
                url = pdf_url_for(doc_id, filing_type, filed_year)
                _record_fetch_failed(filing_id, f"{url} -> {exc}")
                continue

            _record_archived(filing_id, object_key, sha256_hex(content))
            archived += 1
    finally:
        client.close()
    return archived


def candidate_years(filed_year: int) -> list[int]:
    """Clerk folder years to try for a filing, most likely first.

    The Clerk files a PDF under its index year -- the calendar year the
    filing belongs to -- not the year it was filed: an annual report filed
    in March 2016 for 2015 sits in `financial-pdfs/2015/`. Confirmed
    against the Clerk's own yearly indexes (2026-10-08): 4,522 of the
    annual reports in `filings` have a filed year differing from their
    index year, behind most of the ~22k open house_pdf_fetch_failed issues.
    """
    return [filed_year, filed_year - 1, filed_year + 1]


def _fetch_pdf(
    client: httpx.Client, doc_id: str, filing_type: str, filed_year: int
) -> tuple[int, bytes]:
    """(folder year, PDF bytes); raises the last error if no year serves it."""
    last_error: Exception | None = None
    for year in candidate_years(filed_year):
        try:
            response = client.get(pdf_url_for(doc_id, filing_type, year))
            response.raise_for_status()
            return year, response.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            last_error = exc
    assert last_error is not None
    raise last_error


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
        #
        # Within each tier, electronic annual reports (filing_type 'O' with
        # a "100xxxxx" DocID) come right after PTRs: house_fds.py parses
        # them into holdings, and on 2026-10-08 4,126 of them still waited
        # behind ~15k extensions, candidate reports and amendments nobody
        # parses. Only the electronic series is promoted: thousands of old
        # 'O' rows no longer in the Clerk's index 404 forever and would
        # otherwise crowd the batch the way tier 2 describes.
        already_failed = select(DqIssue.filing_id).where(
            DqIssue.issue_type == FETCH_FAILED_ISSUE_TYPE, DqIssue.resolved_at.is_(None)
        )
        failed_priority = case((Filing.filing_id.in_(already_failed), 1), else_=0)
        type_priority = case(
            (Filing.filing_type == "P", 0),
            ((Filing.filing_type == "O") & Filing.filing_id.like("house:100%"), 1),
            else_=2,
        )
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
        for issue in session.scalars(
            select(DqIssue).where(
                DqIssue.filing_id == filing_id,
                DqIssue.issue_type == FETCH_FAILED_ISSUE_TYPE,
                DqIssue.resolved_at.is_(None),
            )
        ):
            issue.resolved_at = datetime.now(UTC)


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
