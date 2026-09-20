"""Shared amount-range parsing for House and Senate PTR filings.

Both sites render amounts as the same standard bands, e.g.
"$1,001 - $15,000" or "Over $50,000,000".
"""


def parse_amount_range(raw: str) -> tuple[float | None, float | None]:
    raw = raw.strip()
    if not raw:
        return None, None
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
