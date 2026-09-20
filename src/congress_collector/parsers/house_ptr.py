"""Parse House PTR PDFs (FilingType 'P') into structured transactions.

Layout confirmed live from a GitHub Actions runner (this sandbox's egress
proxy blocks the source domain): the form uses a fixed column template --
the same x0 word positions for Owner/Asset/Transaction Type/Date/
Notification Date/Amount appear across different filings. This parses via
``extract_words()`` and those column boundaries rather than
``extract_tables()``, whose table detector merges wrapped cells and
garbled annotation lines into the transaction data. When an amount range
wraps onto a second line ("$15,001 -" / "$50,000"), the wrapped half
lands at the same x0 as the first half, one line down -- also confirmed
live -- which is what makes column-based reconstruction work here.

The form's annotation labels ("Filing Status:", "Subholding Of:",
"Description:", "Location:", ...) render with only their first letter as
real text and the rest as NUL bytes -- a font/encoding quirk of the form
itself. A visual line whose first word contains a NUL byte starts an
annotation block (which can itself span several more lines, e.g. a long
"Description:" of the underlying trades in a bundled sale); it and every
line after it are skipped until a blank line or the start of the next
transaction, since none of these values map to a column in the
`transactions` table.

The "Cap. Gains > $200?" column is a checkbox rendered as vector
graphics, not text -- extract_words() never sees its value, so it isn't
captured here, and `transactions` has no column for it either.
"""

import io
import re
from dataclasses import dataclass

import pdfplumber

FOOTER_MARKER = "For the complete list of asset type abbreviations"

# Column x0 boundaries in points, derived from the header row's real word
# positions (stable across filings -- same form template). A word's zone
# is [previous boundary, this boundary).
OWNER_MAX_X = 100.0
ASSET_MAX_X = 260.0
TX_TYPE_MAX_X = 325.0
TX_DATE_MAX_X = 380.0
NOTIF_DATE_MAX_X = 445.0
AMOUNT_MAX_X = 524.0

_ROW_TOLERANCE = 3.0

_OWNER_CODES = {"SP": "spouse", "JT": "joint", "DC": "child"}
_TX_TYPE_CODES = {"P": "purchase", "S": "sale_full", "E": "exchange"}

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TX_TYPE_RE = re.compile(r"^(P|S|E)$")
_TICKER_TYPE_RE = re.compile(r"\(([A-Za-z0-9.\-/]{1,15})\)\s*\[([A-Za-z]{1,4})\]\s*$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float


@dataclass(frozen=True)
class ParsedTransaction:
    row_index: int
    owner: str | None
    asset_description_raw: str
    ticker: str | None
    asset_type: str | None
    tx_type: str | None
    tx_date: str | None  # ISO yyyy-mm-dd
    notification_date: str | None
    amount_min: float | None
    amount_max: float | None


def extract_pages_words(pdf_bytes: bytes) -> list[list[Word]]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [
            [Word(text=w["text"], x0=w["x0"], top=w["top"]) for w in page.extract_words()]
            for page in pdf.pages
        ]


def is_electronic(pages_words: list[list[Word]]) -> bool:
    """True if this looks like a text-layer PDF we can parse, rather than
    a scanned image (paper filing)."""
    all_text = [w.text for words in pages_words for w in words]
    return any("Notification" in t for t in all_text) and any("Transaction" in t for t in all_text)


def parse_ptr_transactions(pages_words: list[list[Word]]) -> list[ParsedTransaction]:
    results: list[ParsedTransaction] = []
    current: _OpenRecord | None = None
    in_annotation_block = False
    row_index = 0

    for words in pages_words:
        started = False
        for line in _group_lines(words):
            if not line:
                in_annotation_block = False
                continue

            line_text = " ".join(w.text for w in line)

            if not started:
                if "$200?" in line_text:
                    started = True
                continue

            if FOOTER_MARKER in line_text:
                started = False
                continue

            if _line_starts_transaction(line):
                if current is not None:
                    results.append(current.finalize(row_index))
                    row_index += 1
                current = _OpenRecord.from_line(line)
                in_annotation_block = False
                continue

            if "\x00" in line[0].text:
                in_annotation_block = True
                continue

            if in_annotation_block:
                continue

            if current is not None:
                current.extend(line)

    if current is not None:
        results.append(current.finalize(row_index))

    return results


def _group_lines(words: list[Word]) -> list[list[Word]]:
    """Cluster words into visual lines by `top`, in reading order."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.top, w.x0))
    lines: list[list[Word]] = []
    current_line: list[Word] = [ordered[0]]
    current_top = ordered[0].top
    for word in ordered[1:]:
        if abs(word.top - current_top) <= _ROW_TOLERANCE:
            current_line.append(word)
        else:
            lines.append(sorted(current_line, key=lambda w: w.x0))
            current_line = [word]
            current_top = word.top
    lines.append(sorted(current_line, key=lambda w: w.x0))
    return lines


def _line_starts_transaction(line: list[Word]) -> bool:
    return any(ASSET_MAX_X <= w.x0 < TX_TYPE_MAX_X and _TX_TYPE_RE.match(w.text) for w in line)


@dataclass
class _OpenRecord:
    owner_word: str | None
    asset_parts: list[str]
    tx_type_raw: str
    is_partial: bool
    tx_date: str
    notif_date: str
    amount_parts: list[str]

    @classmethod
    def from_line(cls, line: list[Word]) -> "_OpenRecord":
        owner_word: str | None = None
        asset_parts: list[str] = []
        tx_type_raw = ""
        is_partial = False
        tx_date = ""
        notif_date = ""
        amount_parts: list[str] = []

        for w in line:
            if w.x0 < OWNER_MAX_X:
                if w.text in _OWNER_CODES:
                    owner_word = w.text
            elif w.x0 < ASSET_MAX_X:
                asset_parts.append(w.text)
            elif w.x0 < TX_TYPE_MAX_X:
                if _TX_TYPE_RE.match(w.text):
                    tx_type_raw = w.text
                elif w.text == "(partial)":
                    is_partial = True
            elif w.x0 < TX_DATE_MAX_X:
                if _DATE_RE.match(w.text):
                    tx_date = w.text
            elif w.x0 < NOTIF_DATE_MAX_X:
                if _DATE_RE.match(w.text):
                    notif_date = w.text
            elif w.x0 < AMOUNT_MAX_X:
                amount_parts.append(w.text)

        return cls(
            owner_word=owner_word,
            asset_parts=asset_parts,
            tx_type_raw=tx_type_raw,
            is_partial=is_partial,
            tx_date=tx_date,
            notif_date=notif_date,
            amount_parts=amount_parts,
        )

    def extend(self, line: list[Word]) -> None:
        for w in line:
            if OWNER_MAX_X <= w.x0 < ASSET_MAX_X:
                self.asset_parts.append(w.text)
            elif NOTIF_DATE_MAX_X <= w.x0 < AMOUNT_MAX_X:
                self.amount_parts.append(w.text)

    def finalize(self, row_index: int) -> ParsedTransaction:
        owner = _OWNER_CODES[self.owner_word] if self.owner_word else "self"
        tx_type = _TX_TYPE_CODES.get(self.tx_type_raw)
        if tx_type == "sale_full" and self.is_partial:
            tx_type = "sale_partial"

        asset_description = " ".join(self.asset_parts).strip()
        ticker = None
        asset_type = None
        match = _TICKER_TYPE_RE.search(asset_description)
        if match:
            ticker, asset_type = match.group(1), match.group(2)

        amount_min, amount_max = _parse_amount(" ".join(self.amount_parts))

        return ParsedTransaction(
            row_index=row_index,
            owner=owner,
            asset_description_raw=asset_description,
            ticker=ticker,
            asset_type=asset_type,
            tx_type=tx_type,
            tx_date=_to_iso_date(self.tx_date) if self.tx_date else None,
            notification_date=_to_iso_date(self.notif_date) if self.notif_date else None,
            amount_min=amount_min,
            amount_max=amount_max,
        )


def _parse_amount(raw: str) -> tuple[float | None, float | None]:
    raw = raw.strip()
    if not raw:
        return None, None
    if raw.lower().startswith("over"):
        parts = raw.split("$", 1)
        return (_to_number(parts[1]), None) if len(parts) == 2 else (None, None)
    if "-" not in raw:
        return None, None
    low, high = raw.split("-", 1)
    return _to_number(low), _to_number(high)


def _to_number(raw: str) -> float | None:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_iso_date(raw: str) -> str:
    month, day, year = raw.split("/")
    return f"{year}-{month}-{day}"
