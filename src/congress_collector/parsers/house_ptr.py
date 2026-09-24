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
annotation of the underlying trades in a bundled sale); it and every line
after it are skipped until a blank line or the start of the next
transaction, since none of these values map to a column in the
`transactions` table -- with one exception, added for T15: a
"Description:" block ("D" + NUL run) on an option row (asset_type "OP")
is the only place the form records the option's call/put side, strike
and expiry, so that one label's text is captured and parsed instead of
discarded. Confirmed live (GitHub Actions runner) that filers write this
in at least two styles: a structured one ("Call options; Strike price
$320; Expires 06/18/2026") and an informal one ("10 puts at $11.80",
premium paid per contract, no strike or expiry) -- the informal style is
parsed for option_type only, since guessing a strike from the premium
would be wrong.

The leftmost "ID" column (a 10-digit number, e.g. "2000135564") isn't on
every row -- confirmed live (both the T16 diagnostic and a later
production backfill, ~17 of ~3200 real transactions) that it's specific
to rows involved in an amendment: absent on an ordinary, never-amended
row, present and identical across an original filing and a later "Filing
Status: Amended" row correcting that transaction. That persistence
across filings is what makes cross-filing amendment linking possible at
all (`ingest.amendments`). Sits left of the Owner code, in its own x0
zone, when present.

The "Cap. Gains > $200?" column is a checkbox rendered as vector
graphics, not text -- extract_words() never sees its value, so it isn't
captured here, and `transactions` has no column for it either.

Two form-generation quirks, both confirmed live via a throwaway diagnostic
workflow (2026-09-24) against real pre-2022 filings, were silently causing
a 100% parse-failure rate on every House PTR filed 2015 through most of
2021 (973 of 973 `ptr_parse_failed` filings at the time, before this fix):

1. Filings from roughly 2015-2018 don't have the "Cap. Gains > $200?"
   column at all -- it was added to the form later. `parse_ptr_transactions`
   used to gate on seeing that literal text before starting to read
   transaction rows; on a filing where it never appears, nothing was ever
   read. Fixed by dropping that gate entirely -- `_line_starts_transaction`
   already identifies real transaction rows precisely enough (via the
   Transaction Type column's x0 zone and value) that no separate "have we
   reached the table yet" marker is needed.
2. Filings from roughly 2019-2021 render the single-letter Transaction
   Type code, and the asset-type code inside the asset description's
   brackets, in lowercase in the PDF's stored text layer even though they
   render as (small-caps) uppercase on screen -- confirmed against a 2020
   filing: "3M Company (MMM) [sT] s 03/31/2020 ..." where a 2026 filing's
   equivalent row reads "... [ST] P ...". `_TX_TYPE_RE` and the two
   asset-type regexes are now case-insensitive, with the captured values
   upper-cased before use, so this era parses the same as any other.
3. The same pre-2022 filings render the annotation labels themselves
   ("Filing Status:", "Subholding Of:", "Description:", "Location:") as
   plain mixed-case ASCII text rather than the NUL-byte-padded,
   first-letter-only style 2022+ forms use for the same labels. The
   annotation-block detection only recognized the NUL-byte style, so this
   era's label and content words fell through into `_OpenRecord.extend()`
   and polluted `asset_description_raw` (e.g. "Actavis plc ordinary
   shares (ACT) FILINg sTATus: New subHoLDINg oF: sP M81 (Merrill
   Lynch)"), which broke `_TICKER_TYPE_RE`'s end-of-string anchor and
   silently dropped ticker/asset_type for every affected row. Fixed by
   `_annotation_label()`, which recognizes a label by either encoding.
4. Filings from roughly 2015-2018 (before the "[TYPE]" bracket existed on
   the form at all, alongside the missing Cap. Gains column) have a bare
   "(TICKER)" at the end of the description with no bracket following it
   -- confirmed live: "Actavis plc ordinary shares (ACT)" is the complete
   description, once quirk 3's leaked annotation text is stripped out.
   `_TICKER_TYPE_RE` requires that bracket, so it never matched this era
   even after fixing quirk 3. `_TICKER_ONLY_RE` now catches the bare-ticker
   case; `asset_type` stays `None` for these rows since the era's form
   never recorded it. The extracted ticker is also upper-cased regardless
   of which regex matched, since this era's mixed-case text-layer rendering
   affects the ticker itself too (e.g. "(Cb)" for Chubb, "(gd)" for General
   Dynamics), not just the bracketed type code.
"""

import io
import re
from dataclasses import dataclass

import pdfplumber

from congress_collector.parsers.amounts import parse_amount_range

FOOTER_MARKER = "For the complete list of asset type abbreviations"

# Column x0 boundaries in points, calibrated against the current (2026-era)
# form's header row. Used only as a fallback when a filing's own header
# can't be found (see _detect_column_bounds) -- confirmed live that these
# drift for real between form revisions, not just by a uniform shift: the
# 2019-2021 era's "Transaction Type" column starts at x0=246 vs 2026's
# x0=262, a gap that widens to 14-19pt by the Amount/Cap. Gains columns
# while Owner/Asset barely move (~4pt). A fixed reference table therefore
# misclassifies that era's Transaction Type column as part of Asset. A
# word's zone is [previous boundary, this boundary).
ID_MAX_X = 55.0
OWNER_MAX_X = 100.0
ASSET_MAX_X = 260.0
TX_TYPE_MAX_X = 325.0
TX_DATE_MAX_X = 380.0
NOTIF_DATE_MAX_X = 445.0
AMOUNT_MAX_X = 524.0
_DEFAULT_BOUNDS = (
    ID_MAX_X,
    OWNER_MAX_X,
    ASSET_MAX_X,
    TX_TYPE_MAX_X,
    TX_DATE_MAX_X,
    NOTIF_DATE_MAX_X,
    AMOUNT_MAX_X,
)

_ROW_TOLERANCE = 3.0
_COLUMN_MARGIN = 3.0

_OWNER_CODES = {"SP": "spouse", "JT": "joint", "DC": "child"}
_TX_TYPE_CODES = {"P": "purchase", "S": "sale_full", "E": "exchange"}

# The form's annotation labels, normalized. Confirmed live (2026-09-24
# diagnostic) that pre-2022 filings render these as plain mixed-case ASCII
# text ("FILINg", "sUBHOLDINg oF:", "DESCRIPTION:", "LOCATION:") rather than
# the NUL-byte-padded first-letter-only style 2022+ forms use -- the same
# underlying font quirk, two different eras' rendering of it.
_ANNOTATION_LABELS = {"filing", "subholding", "description", "location"}

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# Case-insensitive: pre-2022 filings render this single-letter code (and the
# asset-type-in-brackets code below) in lowercase in the PDF's text layer --
# confirmed live against a 2020 filing ("3M Company (MMM) [sT] s ...") where
# the visual small-caps rendering doesn't match the underlying stored text --
# even though a 2026 filing's equivalent row renders it uppercase ("P").
_TX_TYPE_RE = re.compile(r"^(P|S|E)$", re.IGNORECASE)
_TICKER_TYPE_RE = re.compile(r"\(([A-Za-z0-9.\-/]{1,15})\)\s*\[([A-Za-z]{1,4})\]\s*$")
_TYPE_ONLY_RE = re.compile(r"\[([A-Za-z]{1,4})\]\s*$")
# Pre-2019 filings (before the "[TYPE]" bracket existed on the form at
# all -- see the module docstring) have a bare "(TICKER)" at the end of
# the description instead, e.g. "Actavis plc ordinary shares (ACT)".
_TICKER_ONLY_RE = re.compile(r"\(([A-Za-z0-9.\-/]{1,15})\)\s*$")

_STRUCTURED_OPTION_RE = re.compile(
    r"(?P<type>call|put)s?\s+options?.*?"
    r"strike\s+price\s*\$(?P<strike>[\d,]+(?:\.\d+)?).*?"
    r"expires?\s*(?P<expiry>\d{2}/\d{2}/\d{4})",
    re.IGNORECASE | re.DOTALL,
)
_INFORMAL_OPTION_RE = re.compile(r"\b(?P<type>calls?|puts?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float


@dataclass(frozen=True)
class _ColumnBounds:
    """Zone boundaries for one document, in points. A word's zone is
    ``[previous boundary, this boundary)``."""

    id_max_x: float
    owner_max_x: float
    asset_max_x: float
    tx_type_max_x: float
    tx_date_max_x: float
    notif_date_max_x: float
    amount_max_x: float


_DEFAULT_COLUMN_BOUNDS = _ColumnBounds(*_DEFAULT_BOUNDS)


@dataclass(frozen=True)
class ParsedTransaction:
    row_index: int
    owner: str | None
    asset_description_raw: str
    ticker: str | None
    asset_type: str | None
    option_type: str | None
    strike: float | None
    expiry: str | None  # ISO yyyy-mm-dd
    tx_type: str | None
    tx_date: str | None  # ISO yyyy-mm-dd
    notification_date: str | None
    amount_min: float | None
    amount_max: float | None
    source_transaction_id: str | None


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


def _detect_column_bounds(pages_words: list[list[Word]]) -> _ColumnBounds:
    """Derive this filing's own column boundaries from its header row.

    Column x0 positions drift between form revisions (see the module
    docstring), so a fixed reference table misclassifies some eras'
    columns. The header words themselves ("Owner", "Asset", "Transaction",
    the row's own "Date", "Notification", "Amount", optionally "Cap.") are
    stable text across every era observed, so locating them directly is
    more robust than trusting any one fixed calibration. Falls back to
    ``_DEFAULT_COLUMN_BOUNDS`` (2026-era) if a header row can't be found at
    all, e.g. a filing with a genuinely unrecognizable layout.
    """
    for words in pages_words:
        for line in _group_lines(words):
            positions = {w.text: w.x0 for w in line}
            if "Owner" not in positions or "Asset" not in positions:
                continue
            if "Transaction" not in positions or "Notification" not in positions:
                continue
            if "Amount" not in positions:
                continue
            # The row's "Date" belongs to the tx-date column when it sits
            # between "Transaction" and "Notification" -- "Notification"'s
            # own "Date" is on the second header line, not this one.
            tx_date_x0 = next(
                (
                    w.x0
                    for w in line
                    if w.text == "Date"
                    and positions["Transaction"] < w.x0 < positions["Notification"]
                ),
                None,
            )
            if tx_date_x0 is None:
                continue
            amount_x0 = positions["Amount"]
            cap_x0 = positions.get("Cap.")
            # A data row's value can start a fraction of a point left of the
            # header label above it (confirmed live: a real "P" transaction-
            # type value at x0=262.2 sits just under its own "Transaction"
            # header at x0=262.3) -- a zone boundary placed exactly at the
            # header's x0 has zero margin for that and misclassifies the
            # value into the previous column. Shifting every boundary left
            # by a few points restores the safety margin the original fixed
            # constants happened to have.
            return _ColumnBounds(
                id_max_x=ID_MAX_X,
                owner_max_x=positions["Asset"] - _COLUMN_MARGIN,
                asset_max_x=positions["Transaction"] - _COLUMN_MARGIN,
                tx_type_max_x=tx_date_x0 - _COLUMN_MARGIN,
                tx_date_max_x=positions["Notification"] - _COLUMN_MARGIN,
                notif_date_max_x=amount_x0 - _COLUMN_MARGIN,
                # No Cap Gains column on the pre-2019 form: give the amount
                # zone the same width it has on the reference form instead
                # of an arbitrary guess.
                amount_max_x=(cap_x0 - _COLUMN_MARGIN)
                if cap_x0 is not None
                else amount_x0 + (AMOUNT_MAX_X - NOTIF_DATE_MAX_X),
            )
    return _DEFAULT_COLUMN_BOUNDS


def parse_ptr_transactions(pages_words: list[list[Word]]) -> list[ParsedTransaction]:
    bounds = _detect_column_bounds(pages_words)
    results: list[ParsedTransaction] = []
    current: _OpenRecord | None = None
    in_annotation_block = False
    describing = False
    row_index = 0

    for words in pages_words:
        past_footer = False
        for line in _group_lines(words):
            if not line:
                in_annotation_block = False
                describing = False
                continue

            line_text = " ".join(w.text for w in line)

            if _is_header_line(line_text):
                # The column header repeats on every continuation page. It
                # must be dropped explicitly now that nothing else gates
                # parsing on "have we reached the table yet": confirmed
                # live -- without this, a record whose amount wraps onto
                # the next page picks up the repeated "Owner Asset ...
                # Cap. Gains" header words via `current.extend()`, since
                # several of them (e.g. "Gains", "Cap.") fall inside the
                # amount column's x0 zone.
                continue

            if FOOTER_MARKER in line_text:
                past_footer = True
                continue

            if past_footer:
                continue

            if _line_starts_transaction(line, bounds):
                if current is not None:
                    results.append(current.finalize(row_index))
                    row_index += 1
                current = _OpenRecord.from_line(line, bounds)
                in_annotation_block = False
                describing = False
                continue

            label = _annotation_label(line[0].text)
            if label is not None:
                in_annotation_block = True
                describing = label == "description"
                if describing and current is not None:
                    current.add_description_words(line)
                continue

            if describing and current is not None:
                current.add_description_words(line)
                continue

            if in_annotation_block:
                continue

            if current is not None:
                current.extend(line, bounds)

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


def _is_header_line(line_text: str) -> bool:
    """True for either of the table's two column-header rows.

    Checked by content rather than position or era-specific text ("$200?"
    doesn't exist on the pre-2019 form -- see the module docstring), so it
    catches the header both at the top of the table and wherever it
    repeats on a continuation page. No real asset description or amount
    line plausibly contains any of these word pairs together.
    """
    return (
        ("Owner" in line_text and "Asset" in line_text)
        or ("Notification" in line_text and "Amount" in line_text)
        or ("Cap." in line_text and "Gains" in line_text)
        or "$200?" in line_text
    )


def _annotation_label(word_text: str) -> str | None:
    """Which annotation label (if any) a line's first word represents.

    Handles both encodings the form uses for the same labels ("Filing
    Status:", "Subholding Of:", "Description:", "Location:") -- the
    NUL-byte-padded, first-letter-only style 2022+ forms render, and the
    plain mixed-case ASCII style pre-2022 forms use instead ("FILINg",
    "sUBHOLDINg", "DESCRIPTION:", "LOCATION:"), confirmed live via the
    2026-09-24 diagnostic workflow. Returns None for an ordinary word.
    """
    if "\x00" in word_text:
        return {
            "F": "filing",
            "S": "subholding",
            "D": "description",
            "L": "location",
        }.get(word_text[0].upper())
    stripped = word_text.rstrip(":").lower()
    return stripped if stripped in _ANNOTATION_LABELS else None


def _line_starts_transaction(line: list[Word], bounds: _ColumnBounds) -> bool:
    return any(
        bounds.asset_max_x <= w.x0 < bounds.tx_type_max_x and _TX_TYPE_RE.match(w.text)
        for w in line
    )


@dataclass
class _OpenRecord:
    id_word: str | None
    owner_word: str | None
    asset_parts: list[str]
    tx_type_raw: str
    is_partial: bool
    tx_date: str
    notif_date: str
    amount_parts: list[str]
    description_parts: list[str]

    @classmethod
    def from_line(cls, line: list[Word], bounds: _ColumnBounds) -> "_OpenRecord":
        id_word: str | None = None
        owner_word: str | None = None
        asset_parts: list[str] = []
        tx_type_raw = ""
        is_partial = False
        tx_date = ""
        notif_date = ""
        amount_parts: list[str] = []

        for w in line:
            if w.x0 < bounds.id_max_x:
                id_word = w.text
            elif w.x0 < bounds.owner_max_x:
                if w.text.upper() in _OWNER_CODES:
                    owner_word = w.text.upper()
            elif w.x0 < bounds.asset_max_x:
                asset_parts.append(w.text)
            elif w.x0 < bounds.tx_type_max_x:
                if _TX_TYPE_RE.match(w.text):
                    tx_type_raw = w.text.upper()
                elif w.text.lower() == "(partial)":
                    is_partial = True
            elif w.x0 < bounds.tx_date_max_x:
                if _DATE_RE.match(w.text):
                    tx_date = w.text
            elif w.x0 < bounds.notif_date_max_x:
                if _DATE_RE.match(w.text):
                    notif_date = w.text
            elif w.x0 < bounds.amount_max_x:
                amount_parts.append(w.text)

        return cls(
            id_word=id_word,
            owner_word=owner_word,
            asset_parts=asset_parts,
            tx_type_raw=tx_type_raw,
            is_partial=is_partial,
            tx_date=tx_date,
            notif_date=notif_date,
            amount_parts=amount_parts,
            description_parts=[],
        )

    def extend(self, line: list[Word], bounds: _ColumnBounds) -> None:
        for w in line:
            if bounds.owner_max_x <= w.x0 < bounds.asset_max_x:
                self.asset_parts.append(w.text)
            elif bounds.notif_date_max_x <= w.x0 < bounds.amount_max_x:
                self.amount_parts.append(w.text)

    def add_description_words(self, line: list[Word]) -> None:
        for w in line:
            if "\x00" in w.text:
                continue  # the "D...:" label word itself, not content
            if w.text.rstrip(":").lower() == "description":
                continue  # plain-text label style (pre-2022 filings)
            self.description_parts.append(w.text)

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
            # .upper() on both: pre-2022 filings render the bracketed type
            # code, and sometimes the ticker itself (e.g. "(Cb)" for
            # Chubb), in lowercase/mixed case in the text layer -- see the
            # _TX_TYPE_RE note above, same underlying font quirk.
            ticker, asset_type = match.group(1).upper(), match.group(2).upper()
        else:
            # No "(TICKER)" -- e.g. government securities, private
            # holdings, and other asset types that don't trade under a
            # ticker -- but the type code in brackets is still present.
            type_match = _TYPE_ONLY_RE.search(asset_description)
            if type_match:
                asset_type = type_match.group(1).upper()
            else:
                # Pre-2019 form: no "[TYPE]" bracket exists on the form at
                # all, just a bare "(TICKER)" at the end.
                ticker_match = _TICKER_ONLY_RE.search(asset_description)
                if ticker_match:
                    ticker = ticker_match.group(1).upper()

        option_type = strike = expiry = None
        if asset_type == "OP":
            option_type, strike, expiry = _parse_option_details(" ".join(self.description_parts))

        amount_min, amount_max = parse_amount_range(" ".join(self.amount_parts))

        return ParsedTransaction(
            row_index=row_index,
            owner=owner,
            asset_description_raw=asset_description,
            ticker=ticker,
            asset_type=asset_type,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            tx_type=tx_type,
            tx_date=_to_iso_date(self.tx_date) if self.tx_date else None,
            notification_date=_to_iso_date(self.notif_date) if self.notif_date else None,
            amount_min=amount_min,
            amount_max=amount_max,
            source_transaction_id=self.id_word,
        )


def _parse_option_details(description: str) -> tuple[str | None, float | None, str | None]:
    match = _STRUCTURED_OPTION_RE.search(description)
    if match:
        strike = float(match.group("strike").replace(",", ""))
        expiry = _to_iso_date(match.group("expiry"))
        return match.group("type").lower(), strike, expiry

    match = _INFORMAL_OPTION_RE.search(description)
    if match:
        # Premium paid per contract, not a strike price -- only the
        # call/put side is reliably extractable from this style.
        return match.group("type").lower().rstrip("s"), None, None

    return None, None, None


def _to_iso_date(raw: str) -> str:
    month, day, year = raw.split("/")
    return f"{year}-{month}-{day}"
