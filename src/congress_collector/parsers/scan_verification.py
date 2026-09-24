"""Sanity-check a vision model's extraction of a scanned PTR filing before
it's allowed anywhere near `transactions`.

Confirmed live (16-filing Haiku 4.5 test batch, 2026-09-24, session
https://claude.ai/code/session_01PTKvPM3DvVAJvwirNCwUsM -- see
`scan_classification.py`'s module docstring for the full test writeup):
extraction failures on RISKY-tier scans aren't limited to the safe,
recognizable case (an empty result, or a model saying it gave up). Two
observed failure modes produce a normal-looking, non-empty list of
transactions that is nonetheless wrong:

1. A dense multi-column matrix form's amount-bracket legend (columns
   "A"-"K" or similar) mistaken for 14 transaction rows, every one with
   `asset_description_raw` left blank -- there is no such thing as a real
   PTR transaction row with no asset description, so this is a clean,
   mechanical tell.
2. A systematically wrong field on an otherwise-plausible, non-empty
   extraction (e.g. one filing's owner code was wrong on every early-page
   row but correct on later pages) -- this class of error has no cheap
   mechanical signature; it was only caught by reading the scan by hand.
   `verify_extraction` cannot catch this, and that gap is deliberate: it
   should never be treated as "verified clean" just because it passed the
   checks here. Callers still need the human-review path this module's
   `needs_review` flag routes filings into.

This is a v1: the checks below catch the specific failure shape #1 above,
plus generic implausibility signals worth a second look. It is not a
substitute for the human-review step the test batch's own recommendation
calls for on every RISKY-tier filing above a modest transaction count.
"""

from collections import Counter
from dataclasses import dataclass

from congress_collector.parsers.house_ptr import ParsedTransaction

# Above this many transactions in one filing, flag for human review
# regardless of whether the mechanical checks below pass -- the test
# batch's one large (23-page, 169-transaction) filing extracted a
# plausible-looking count but had a real, undetected owner-code error on
# its early pages, confirmed only by a manual page-by-page read.
REVIEW_TRANSACTION_COUNT = 20

# A single (owner, description, tx_type, date, amount) combination
# repeated this many times or more in one filing is treated as a likely
# hallucinated-repetition artifact rather than a real filing pattern.
REVIEW_DUPLICATE_COUNT = 3


@dataclass(frozen=True)
class VerificationResult:
    ok: bool  # False means: do not write this extraction to the database
    needs_review: bool  # True means: a human should look before/after writing
    reasons: tuple[str, ...]


def verify_extraction(transactions: list[ParsedTransaction]) -> VerificationResult:
    reasons: list[str] = []
    ok = True
    needs_review = False

    blank_rows = sum(1 for t in transactions if not t.asset_description_raw.strip())
    if blank_rows:
        ok = False
        reasons.append(
            f"{blank_rows} of {len(transactions)} row(s) have a blank asset_description_raw "
            "-- no real PTR transaction row lacks a description; this shape matches a legend "
            "or table header mistaken for transaction rows"
        )

    if len(transactions) > REVIEW_TRANSACTION_COUNT:
        needs_review = True
        reasons.append(
            f"{len(transactions)} transactions exceeds the {REVIEW_TRANSACTION_COUNT}-row "
            "auto-accept threshold -- large filings had undetected field-level errors in "
            "the test batch even when the row count itself looked plausible"
        )

    dupe_counts = Counter(
        (t.owner, t.asset_description_raw, t.tx_type, t.tx_date, t.amount_min, t.amount_max)
        for t in transactions
    )
    worst_dupe = max(dupe_counts.values(), default=0)
    if worst_dupe >= REVIEW_DUPLICATE_COUNT:
        needs_review = True
        reasons.append(
            f"a single (owner, description, type, date, amount) combination repeats "
            f"{worst_dupe} times -- checking for a hallucinated-repetition artifact"
        )

    if not transactions:
        needs_review = True
        reasons.append(
            "zero transactions extracted -- could be a genuinely empty filing, or the model "
            "giving up on a poor scan; both look identical from this output alone"
        )

    return VerificationResult(ok=ok, needs_review=needs_review, reasons=tuple(reasons))
