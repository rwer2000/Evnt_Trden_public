"""Re-parse electronic House PTR filings that have transactions with a null
`amount_min`, and fill the amount in from the current parser.

On 2026-10-11 this was 698 transactions in 303 filings. Parsing every one
of those filings' public PDFs locally sorted them into:

- ~510 rows reporting an exact dollar value ("$2,722.50") instead of a
  band, and ~134 rows with the "Spouse/DC Over $1,000,000" band -- shapes
  `parsers.amounts.parse_amount_range` didn't recognize until now;
- ~25 rows parsed in September 2026 by a parser version whose fixed column
  bounds dropped the amount and shifted the notification date into
  `tx_date` (e.g. Pelosi's DocID 20026590), which today's per-filing
  column detection already parses correctly but nothing re-ran;
- 15 phantom rows ("DESCRIPTION: PUT BABA Nov 19 21 155.0") created when a
  Description annotation held a lone "P"/"S" in the Transaction Type
  column; the parser no longer produces these;
- 9 rows of scanned (transcribed) filings, which this script leaves alone.

What it changes, per transaction still missing `amount_min`:

- If the re-parsed filing has a row at the same `row_index` with the same
  `asset_description_raw` (or, failing that, exactly one row with the same
  description, `tx_type` and owner), its amount is copied over. If the
  stored row also has no `notification_date` while the parsed row does,
  `tx_date` and `notification_date` are taken from the parse too: that is
  the signature of the stale fixed-bounds parse described above, where the
  stored `tx_date` is really the notification date.
- A row whose description starts with an annotation label ("DESCRIPTION:",
  "FILING STATUS:", ...) and that matches no parsed row is a phantom. It is
  only deleted with ``--delete-phantoms``, and only when no `dq_issues` row
  points at it.
- Anything else is reported and left alone.

Dry run by default: nothing is written without ``--apply``. Safe to re-run;
once caught up it finds nothing to do. Run manually via the
`reparse-house-ptr-amounts` workflow, or locally:

    uv run python -m congress_collector.ingest.reparse_house_ptr_amounts
        # optional flags: --apply  --delete-phantoms
"""

import argparse
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select

from congress_collector.db.models import DqIssue, Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.parsers.house_ptr import (
    ParsedTransaction,
    extract_pages_words,
    parse_ptr_transactions,
)
from congress_collector.storage.r2_storage import download

_PHANTOM_RE = re.compile(
    r"^(?:description|filing\s+status|subholding\s+of|location)\s*:", re.IGNORECASE
)


@dataclass(frozen=True)
class StoredRow:
    transaction_id: uuid.UUID
    row_index: int
    asset_description_raw: str
    tx_type: str
    owner: str | None
    notification_date: date | None


@dataclass(frozen=True)
class AmountFix:
    transaction_id: uuid.UUID
    amount_min: float
    amount_max: float | None
    # Set only when the stored dates come from the stale fixed-bounds parse.
    tx_date: date | None
    notification_date: date | None


@dataclass
class FilingPlan:
    fixes: list[AmountFix] = field(default_factory=list)
    phantoms: list[uuid.UUID] = field(default_factory=list)
    unmatched: int = 0  # no matching parsed row
    no_amount: int = 0  # matched, but the parse has no amount either


@dataclass
class Summary:
    filings: int = 0
    download_failed: int = 0
    fixed: int = 0
    dates_fixed: int = 0
    phantoms_found: int = 0
    phantoms_deleted: int = 0
    unmatched: int = 0
    no_amount: int = 0


def _norm(text: str) -> str:
    return " ".join(text.split())


def plan_filing(stored: list[StoredRow], parsed: list[ParsedTransaction]) -> FilingPlan:
    """Decide, without touching the database, what to change for one
    filing's amount-less rows given a fresh parse of its PDF."""
    plan = FilingPlan()
    by_index = {t.row_index: t for t in parsed}
    for row in stored:
        match = _match(row, by_index, parsed)
        if match is None:
            if _PHANTOM_RE.match(row.asset_description_raw):
                plan.phantoms.append(row.transaction_id)
            else:
                plan.unmatched += 1
            continue
        if match.amount_min is None:
            plan.no_amount += 1
            continue
        stale_dates = row.notification_date is None and match.notification_date is not None
        plan.fixes.append(
            AmountFix(
                transaction_id=row.transaction_id,
                amount_min=match.amount_min,
                amount_max=match.amount_max,
                tx_date=_iso(match.tx_date) if stale_dates else None,
                notification_date=_iso(match.notification_date) if stale_dates else None,
            )
        )
    return plan


def _match(
    row: StoredRow, by_index: dict[int, ParsedTransaction], parsed: list[ParsedTransaction]
) -> ParsedTransaction | None:
    description = _norm(row.asset_description_raw)
    same_index = by_index.get(row.row_index)
    if same_index is not None and _norm(same_index.asset_description_raw) == description:
        return same_index
    candidates = [
        t
        for t in parsed
        if _norm(t.asset_description_raw) == description
        and t.tx_type == row.tx_type
        and t.owner == row.owner
    ]
    return candidates[0] if len(candidates) == 1 else None


def _iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def reparse_amounts(*, apply: bool, delete_phantoms: bool) -> Summary:
    summary = Summary()
    for filing_id, object_key in _affected_filings():
        summary.filings += 1
        try:
            parsed = parse_ptr_transactions(extract_pages_words(download(object_key)))
        except Exception as exc:  # report the type only, never details
            summary.download_failed += 1
            print(f"{filing_id}: download/parse failed ({type(exc).__name__})")
            continue

        stored = _stored_rows(filing_id)
        plan = plan_filing(stored, parsed)
        summary.fixed += len(plan.fixes)
        summary.dates_fixed += sum(1 for f in plan.fixes if f.notification_date is not None)
        summary.phantoms_found += len(plan.phantoms)
        summary.unmatched += plan.unmatched
        summary.no_amount += plan.no_amount
        if plan.unmatched or plan.no_amount:
            print(f"{filing_id}: {plan.unmatched} unmatched, {plan.no_amount} still without amount")
        if apply:
            summary.phantoms_deleted += _apply(plan, delete_phantoms=delete_phantoms)
    return summary


def _affected_filings() -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.execute(
            select(Filing.filing_id, Filing.raw_object_key)
            .join(Transaction, Transaction.filing_id == Filing.filing_id)
            .where(
                Filing.chamber == "house",
                Filing.filing_type == "P",
                Filing.format == "electronic",
                Filing.raw_object_key.is_not(None),
                Transaction.amount_min.is_(None),
            )
            .distinct()
            .order_by(Filing.filing_id)
        ).all()
        return [(filing_id, key) for filing_id, key in rows if key]


def _stored_rows(filing_id: str) -> list[StoredRow]:
    with session_scope() as session:
        rows = session.scalars(
            select(Transaction).where(
                Transaction.filing_id == filing_id, Transaction.amount_min.is_(None)
            )
        ).all()
        return [
            StoredRow(
                transaction_id=t.transaction_id,
                row_index=t.row_index,
                asset_description_raw=t.asset_description_raw,
                tx_type=t.tx_type,
                owner=t.owner,
                notification_date=t.notification_date,
            )
            for t in rows
        ]


def _apply(plan: FilingPlan, *, delete_phantoms: bool) -> int:
    """Writes one filing's plan in one transaction; returns phantoms deleted."""
    deleted = 0
    with session_scope() as session:
        for fix in plan.fixes:
            tx = session.get(Transaction, fix.transaction_id)
            if tx is None or tx.amount_min is not None:
                continue  # gone or already fixed by a concurrent run
            tx.amount_min = fix.amount_min
            tx.amount_max = fix.amount_max
            if fix.notification_date is not None:
                tx.tx_date = fix.tx_date
                tx.notification_date = fix.notification_date

        if delete_phantoms and plan.phantoms:
            referenced = set(
                session.scalars(
                    select(DqIssue.transaction_id).where(DqIssue.transaction_id.in_(plan.phantoms))
                ).all()
            )
            deletable = [tid for tid in plan.phantoms if tid not in referenced]
            if deletable:
                session.execute(
                    delete(Transaction).where(Transaction.transaction_id.in_(deletable))
                )
                deleted = len(deletable)
    return deleted


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument(
        "--delete-phantoms",
        action="store_true",
        help="with --apply, also delete phantom annotation rows",
    )
    args = parser.parse_args(argv)

    s = reparse_amounts(apply=args.apply, delete_phantoms=args.delete_phantoms)
    mode = "APPLIED" if args.apply else "DRY RUN (pass --apply to write)"
    print(
        f"House PTR amount re-parse [{mode}]: {s.filings} filing(s); "
        f"{s.fixed} amount(s) filled ({s.dates_fixed} with corrected dates); "
        f"{s.phantoms_found} phantom row(s) found, {s.phantoms_deleted} deleted; "
        f"{s.unmatched} unmatched; {s.no_amount} still without amount; "
        f"{s.download_failed} download/parse failure(s)."
    )


if __name__ == "__main__":
    main()
