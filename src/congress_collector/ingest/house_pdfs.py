"""Download House Clerk PDFs for filings not yet archived, and store them
in Supabase Storage with a SHA-256 hash.

Classifying a filing as electronic/paper/scanned needs the PDF itself, so
that stays `format = 'unknown'` here and is T8's job.
"""

from datetime import UTC, date, datetime

import httpx
from sqlalchemy import case, select

from congress_collector.db.models import Filing
from congress_collector.db.session import session_scope
from congress_collector.sources.house import USER_AGENT, pdf_url_for
from congress_collector.storage.supabase_storage import sha256_hex, upload

BATCH_SIZE = 50


def archive_pending_house_pdfs(*, batch_size: int = BATCH_SIZE) -> int:
    """Download+archive PDFs for up to `batch_size` House filings that
    don't have one yet. Returns the number successfully archived; filings
    whose PDF couldn't be fetched are left pending for the next run."""
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
            except httpx.HTTPError:
                continue

            content = response.content
            object_key = f"house/{year}/{doc_id}.pdf"
            upload(object_key, content, "application/pdf")
            _record_archived(filing_id, object_key, sha256_hex(content))
            archived += 1
    finally:
        client.close()
    return archived


def main() -> None:
    archived = archive_pending_house_pdfs()
    print(f"House PDF archive: {archived} filing(s) archived.")


def _fetch_pending(limit: int) -> list[tuple[str, str, str, date | None]]:
    with session_scope() as session:
        # Periodic transaction reports (filing_type 'P') first: they're
        # the only type house_ptrs.py ever parses into transactions, but
        # this table is dominated by other filing types (annual reports,
        # amendments, extensions, ...) that will sit archived and
        # otherwise untouched forever. Without this ordering, those types
        # compete for the same limited per-run budget and a PTR backlog
        # (e.g. from T20's backfill) can take months to catch up even
        # though it's the only part that actually blocks parsing --
        # confirmed live: 395/7,666 House PTRs archived weeks after the
        # backfill landed, most of this step's budget spent on the other
        # ~40k non-PTR filings instead.
        priority = case((Filing.filing_type == "P", 0), else_=1)
        rows = session.execute(
            select(Filing.filing_id, Filing.filing_type, Filing.filed_date)
            .where(Filing.chamber == "house", Filing.raw_object_key.is_(None))
            .order_by(priority)
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


if __name__ == "__main__":
    main()
