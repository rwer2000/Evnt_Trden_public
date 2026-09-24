"""Triage House scanned (`format = 'scanned'`) PTR filings into risk tiers
by their House-assigned document ID, before spending anything (a vision
model call, a human reviewer's time) on the PDF itself.

Confirmed live via a throwaway 16-filing test batch (Haiku 4.5 vision
extraction against real scanned House PTRs, spread 2015-2026, cross-checked
by hand against each scan -- 2026-09-24, session
https://claude.ai/code/session_01PTKvPM3DvVAJvwirNCwUsM): the House Clerk's
scanned-PTR document IDs fall into two distinct numbering series, and which
series a filing is in predicts extraction risk far better than anything
cheaply derivable from the PDF itself (word count, image count/DPI -- all
of `format = 'scanned'` is genuinely image-only; there is no free "actually
has a text layer" subset to reclassify, confirmed live against 25 more
samples: every one had `is_electronic() == False` even where pdfplumber
extracted 100-900 words of unrelated coversheet/letterhead text).

The two series, and what each looked like in the test batch:

- **CLEAN** (8 digits starting "20", e.g. `20016829`): a
  cleanly laid-out, checkbox-style scanned form. Haiku extracted these
  essentially perfectly, including a 4-page/22-transaction filing that
  matched a manual count exactly. This series only appears in filings
  filed 2015 through 2022 -- confirmed live it never appears after that,
  so it is a closed, historical-only bucket, not something the live tool
  needs to plan around.
- **RISKY** (7 digits starting "8" or "9", e.g. `9107579`, `8218645`): old
  rotated paper grid forms, dense multi-column matrices, and handwritten
  filings. Haiku's failures here weren't random noise -- they clustered
  into two dangerous patterns: (1) silent fabrication that looks
  plausible (invented company names, a systematically wrong owner code
  across dozens of real rows, a bracket-amount legend hallucinated as 14
  transaction rows with every description left blank) and (2) partial
  extraction with no signal that anything was missed (half a filing's
  transactions silently dropped). Confirmed live: this is the *only*
  series still in use for scanned filings from 2023 onward -- every
  currently-arriving scanned House PTR is in this riskier bucket, which
  is exactly the population the live notifications tool would need to
  handle if scan support is ever wired into it.

`format = 'scanned'` filings outside both patterns (an id that isn't a
plain 7 or 8 digit number in one of the shapes above) are UNKNOWN -- not confirmed
against either series in the test batch, so treated as the riskier case
until proven otherwise.
"""

import re
from enum import Enum

_CLEAN_ID_RE = re.compile(r"^20\d{6}$")
_RISKY_ID_RE = re.compile(r"^[89]\d{6}$")


class ScanTier(Enum):
    CLEAN = "clean"
    RISKY = "risky"
    UNKNOWN = "unknown"


def classify_scan_tier(filing_id: str) -> ScanTier:
    """Classify a House PTR filing_id (e.g. "house:20016829" or
    "house:8218645") by its document-ID series. Doesn't touch the PDF --
    this is a same-cost-as-a-dict-lookup triage step meant to run before
    any download or model call.
    """
    doc_id = filing_id.split(":", 1)[-1]
    if _CLEAN_ID_RE.match(doc_id):
        return ScanTier.CLEAN
    if _RISKY_ID_RE.match(doc_id):
        return ScanTier.RISKY
    return ScanTier.UNKNOWN
