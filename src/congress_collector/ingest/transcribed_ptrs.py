"""Import transcribed scanned House PTRs into `transactions`.

Scanned House PTRs (the "8/9xxxxxx" DocID series) have no text layer, so
`ingest.house_ptrs` leaves them `paper_deferred`. Some are transcribed
outside this pipeline: each PDF read by two independent Claude vision
passes, disagreements resolved by a third look at the scan, the result a
CSV under `data/` (one row per transaction, with the source DocID). First
batch, 2026-10-09: the 89 PTRs of the 57 filers who missed only 1-3
filings; both readings agreed on every transaction date and amount band.

The import adds the rows as ordinary transactions (so the regular ticker
linking picks them up) and records each in `transaction_provenance` with
method 'transcribed', the combined confidence and the review note. The
filing becomes `parse_status = 'parsed'` while keeping `format =
'scanned'` -- that pair marks a transcribed filing. Filings that are no
longer `paper_deferred`/`failed`, or already have transactions, are left
alone, so a rerun is a no-op. Rows the form leaves without a transaction
type (the column is NOT NULL) get a dq_issues row instead, the same as the
parser's unknown_tx_type.

Run manually via `import-transcribed-ptrs.yml` (workflow_dispatch), with
the CSV path as input.
"""

import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from congress_collector.db.models import DqIssue, Filing, Transaction, TransactionProvenance
from congress_collector.db.session import session_scope
from congress_collector.parsers.amounts import parse_amount_range

METHOD = "transcribed"
# The House PTR form's amount columns.
AMOUNT_BANDS = {
    "A": "$1,001 - $15,000",
    "B": "$15,001 - $50,000",
    "C": "$50,001 - $100,000",
    "D": "$100,001 - $250,000",
    "E": "$250,001 - $500,000",
    "F": "$500,001 - $1,000,000",
    "G": "$1,000,001 - $5,000,000",
    "H": "$5,000,001 - $25,000,000",
    "I": "$25,000,001 - $50,000,000",
    "J": "Over $50,000,000",
}
_TX_TYPES = {"purchase", "sale_full", "sale_partial", "exchange"}
_OWNERS = {"self", "spouse", "joint", "child"}
_TICKER_IN_NAME = re.compile(r"\(([A-Z][A-Z.\-]{0,5})\)\s*$")


@dataclass(frozen=True)
class TranscribedRow:
    filing_id: str
    asset_description_raw: str
    ticker: str | None
    owner: str | None
    tx_type: str | None
    tx_date: date | None
    notification_date: date | None
    amount_min: float | None
    amount_max: float | None
    confidence: str | None
    review: str | None
    note: str | None


def read_csv(path: Path) -> tuple[dict[str, list[TranscribedRow]], set[str]]:
    """(transaction rows per filing_id, filing_ids with no transactions)."""
    by_filing: dict[str, list[TranscribedRow]] = defaultdict(list)
    empty: set[str] = set()
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            filing_id = f"house:{raw['doc_id'].strip()}"
            name = (raw["asset_name"] or "").strip()
            if not name:
                empty.add(filing_id)
                continue
            by_filing[filing_id].append(_to_row(filing_id, name, raw))
    return dict(by_filing), empty - set(by_filing)


def _to_row(filing_id: str, name: str, raw: dict[str, str]) -> TranscribedRow:
    ticker = (raw["ticker"] or "").strip().upper() or None
    if ticker is None and (m := _TICKER_IN_NAME.search(name.upper())):
        ticker = m.group(1)
    band = (raw["amount_band"] or "").strip().upper()
    amount_min, amount_max = parse_amount_range(AMOUNT_BANDS.get(band, ""))
    tx_type = (raw["tx_type"] or "").strip() or None
    owner = (raw["owner"] or "").strip() or None
    return TranscribedRow(
        filing_id=filing_id,
        asset_description_raw=name,
        ticker=ticker,
        owner=owner if owner in _OWNERS else None,
        tx_type=tx_type if tx_type in _TX_TYPES else None,
        tx_date=_date(raw["tx_date"]),
        notification_date=_date(raw["notification_date"]),
        amount_min=amount_min,
        amount_max=amount_max,
        confidence=(raw["confidence"] or "").strip() or None,
        review=(raw["review"] or "").strip() or None,
        note=(raw["note"] or "").strip() or None,
    )


def _date(value: str | None) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def import_csv(path: Path) -> tuple[int, int, int]:
    """Returns (filings imported, transactions added, filings skipped)."""
    by_filing, empty = read_csv(path)
    imported = added = skipped = 0
    for filing_id in sorted(set(by_filing) | empty):
        rows = by_filing.get(filing_id, [])
        with session_scope() as session:
            filing = session.get(Filing, filing_id)
            existing = session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.filing_id == filing_id)
            )
            if (
                filing is None
                or filing.parse_status not in ("paper_deferred", "failed")
                or existing
            ):
                skipped += 1
                continue
            for index, row in enumerate(rows):
                if row.tx_type is None:
                    session.add(
                        DqIssue(
                            filing_id=filing_id,
                            issue_type="unknown_tx_type",
                            details=f"transcribed row {index}: no transaction type on the form "
                            f"({row.asset_description_raw})",
                        )
                    )
                    continue
                tx = Transaction(
                    filing_id=filing_id,
                    row_index=index,
                    owner=row.owner,
                    asset_description_raw=row.asset_description_raw,
                    ticker=row.ticker,
                    tx_type=row.tx_type,
                    tx_date=row.tx_date,
                    notification_date=row.notification_date,
                    amount_min=row.amount_min,
                    amount_max=row.amount_max,
                )
                session.add(tx)
                session.flush()  # assigns transaction_id
                session.add(
                    TransactionProvenance(
                        transaction_id=tx.transaction_id,
                        method=METHOD,
                        confidence=row.confidence,
                        review=row.review,
                        note=row.note,
                        source_file=path.name,
                    )
                )
                added += 1
            filing.parse_status = "parsed"  # format stays 'scanned': transcribed
            imported += 1
    return imported, added, skipped


def main() -> None:
    path = Path(sys.argv[1])
    imported, added, skipped = import_csv(path)
    print(
        f"Transcribed PTRs ({path.name}): {imported} filing(s) imported, "
        f"{added} transaction(s) added, {skipped} skipped."
    )


if __name__ == "__main__":
    main()
