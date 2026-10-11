"""Shared amount-range parsing for House and Senate PTR filings.

Both sites render amounts as the same standard bands, e.g.
"$1,001 - $15,000" or "Over $50,000,000".

Three more shapes, confirmed against the public House PTR PDFs of the
698 House transactions that had a null amount_min on 2026-10-11:

- An exact dollar value instead of a band ("$2,722.50", "$.01"): the House
  form lets a filer report the exact amount, which ~510 of those rows do
  (mostly small dividend reinvestments). Parsed as min == max == value,
  unless the value is exactly a standard band's lower bound ("$15,001"),
  which more likely means a band whose upper half was lost.
- "Spouse/DC Over $1,000,000": the House form's special band for an asset
  held by a spouse or dependent child worth more than $1,000,000 (~134
  rows). Parsed like any other "Over $X" band.
- A band separated by a soft hyphen (U+00AD) instead of "-", with unrelated
  text after it ("$15,001 \\xad $50,000 correct to the best" -- a 2019 filing
  whose certification line falls inside the amount column). The band is
  taken from the start of the string and trailing text is ignored.
"""

import re

_MONEY = r"\$\s*(\d[\d,]*(?:\.\d+)?|\.\d+)"
# Hyphen, soft hyphen, en dash, em dash, minus sign.
_DASH = r"[-\u00ad\u2013\u2014\u2212]"
_RANGE_RE = re.compile(rf"^{_MONEY}\s*{_DASH}\s*{_MONEY}")
_OVER_RE = re.compile(rf"^(?:spouse/dc\s+)?over\s*{_MONEY}", re.IGNORECASE)
_EXACT_RE = re.compile(rf"^{_MONEY}$")
# The lower bounds of the standard bands. A lone "$15,001" is far more
# likely a band whose upper half got lost (e.g. a wrap onto a page we
# didn't read) than an exact amount, so it is not taken as one.
_BAND_LOWER_BOUNDS = {
    1_001.0,
    15_001.0,
    50_001.0,
    100_001.0,
    250_001.0,
    500_001.0,
    1_000_001.0,
    5_000_001.0,
    25_000_001.0,
    50_000_001.0,
}


def parse_amount_range(raw: str) -> tuple[float | None, float | None]:
    raw = raw.strip()
    if not raw:
        return None, None

    match = _RANGE_RE.match(raw)
    if match:
        return to_number(match.group(1)), to_number(match.group(2))

    match = _OVER_RE.match(raw)
    if match:
        return to_number(match.group(1)), None

    match = _EXACT_RE.match(raw)
    if match:
        value = to_number(match.group(1))
        if value is None or value in _BAND_LOWER_BOUNDS:
            return None, None
        return value, value

    # Legacy fallback for anything else with a dash, e.g. a band whose
    # halves aren't both "$"-prefixed ("1,001 - 15,000").
    if raw.lower().startswith("over"):
        parts = raw.split("$", 1)
        return (to_number(parts[1]), None) if len(parts) == 2 else (None, None)
    if "-" not in raw:
        return None, None
    low, high = raw.split("-", 1)
    return to_number(low), to_number(high)


def to_number(raw: str) -> float | None:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
