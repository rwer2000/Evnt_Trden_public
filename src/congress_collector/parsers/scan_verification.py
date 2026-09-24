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

v2 (2026-09-24, same day, extraction_prompt_v2.txt re-test against the 6
worst filings -- see `tests/fixtures/scanned_house_ptr_llm_testset/
v2_prompt_retest.json`) confirmed none of the checks above catch
under-extraction: a plausible-looking but incomplete result, where the
model reads real data correctly for the rows it did extract but silently
stops partway through a dense filing. Two live examples, both large
filings the model was allowed to look at in full: `house:8218645`
extracted 20 of an estimated 100+ transactions, and `house:8220570`
extracted 169 of an estimated 300-400. Both a `reported_total_rows` check
and a page-count heuristic are added for this -- see their own
docstrings below for exactly how weak the evidence behind each is.
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

# Below this many transactions per page, a multi-page filing is flagged as
# a possible under-extraction. Calibrated against exactly 3 known data
# points, so treat this as a weak, advisory-only signal, not a validated
# threshold: house:20019240 (4 pages, 22 correct transactions) sits at
# 5.5/page and is fine; house:8218645 (6 pages, 20 of an estimated 100+)
# sits at 3.3/page and is a real undercount; house:8220570 (23 pages, 169
# of an estimated 300-400) sits at 7.3/page and is also a real undercount.
# A threshold below the correct case's 5.5 and above neither undercount
# would need to sit between 5.5 and everything below it, which the two bad
# cases don't consistently satisfy (8220570's 7.3 is actually above
# 20019240's 5.5) -- there is no clean separating threshold in this data.
# Kept at a level that only flags PAGES_FOR_DENSITY_CHECK-or-more page
# filings with a rate clearly below the one known-good case, accepting
# that this will miss real undercounts (like 8220570) and is only useful
# alongside the other checks, never alone.
MIN_TRANSACTIONS_PER_PAGE = 4.0
PAGES_FOR_DENSITY_CHECK = 4


@dataclass(frozen=True)
class VerificationResult:
    ok: bool  # False means: do not write this extraction to the database
    needs_review: bool  # True means: a human should look before/after writing
    reasons: tuple[str, ...]


def verify_extraction(
    transactions: list[ParsedTransaction],
    *,
    reported_total_rows: int | None = None,
    page_count: int | None = None,
) -> VerificationResult:
    """`reported_total_rows` and `page_count` are both optional, independent
    signals a caller may not have: `reported_total_rows` requires the
    extraction prompt to ask the model for a self-reported row count
    alongside its transactions (not part of `extraction_prompt.txt` or
    `extraction_prompt_v2.txt` -- would need a new prompt variant), and
    `page_count` requires knowing the source PDF's page count (e.g. via
    `house_ptr.extract_pages_words()`). Both are skipped silently when not
    given, since callers before this feature existed have neither."""
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

    if reported_total_rows is not None and reported_total_rows != len(transactions):
        needs_review = True
        reasons.append(
            f"model self-reported {reported_total_rows} row(s) visible but only "
            f"{len(transactions)} were extracted -- it may know it under- or over-counted"
        )

    if (
        page_count is not None
        and page_count >= PAGES_FOR_DENSITY_CHECK
        and transactions
        and len(transactions) / page_count < MIN_TRANSACTIONS_PER_PAGE
    ):
        needs_review = True
        reasons.append(
            f"{len(transactions)} transactions over {page_count} pages "
            f"({len(transactions) / page_count:.1f}/page) is below the "
            f"{MIN_TRANSACTIONS_PER_PAGE}/page floor for a multi-page filing -- low-confidence "
            "signal (see module docstring), worth a look but not a rejection on its own"
        )

    return VerificationResult(ok=ok, needs_review=needs_review, reasons=tuple(reasons))
