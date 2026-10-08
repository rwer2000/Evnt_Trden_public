"""Parse Schedule A ("Assets and 'Unearned' Income") of House annual
Financial Disclosure reports (FilingType 'O') into holdings.

Annual reports list what a member, their spouse and dependent children
hold at year end, with the value as a band. PTRs only show trades, so
anything bought before a member's first PTR (or before the STOCK Act) and
never traded since is invisible without these. Confirmed on 80 electronic
2018 reports of PTR-filing members (2026-10-08): 765 of the 1,743 ticker
holdings on Schedule A never appear in that member's PTRs.

Same form family as the PTR (``parsers.house_ptr``): a fixed column
template located through its header row, the same scrambled-case text
layer, owner codes, "(TICKER) [TYPE]" asset descriptions and value bands.
The header row reads "asset owner value of asset income type(s) income
tx. > $1,000?", repeated on every continuation page. Shapes handled,
all seen on real reports:

- a value band wrapping onto the next line ("$100,001 -" / "$250,000"),
  and an asset description wrapping the same way;
- sub-holdings written as "Account ⇒" on one line and the held asset on
  the next ("Fidelity Investments ⇒" / "SEP: FIDELITY CASH RESERVES [MF]");
- annotation lines ("DESCRIPTION:", "LOCATION:", "SUBHOLDING OF:",
  "COMMENTS:") that belong to the row above and are skipped;
- checkbox glyphs in the "tx. > $1,000?" column ("gfedc", "c" ... "g").

Only electronic reports parse; a scanned paper report has no text layer
and is reported as such by ``is_electronic_fd``.
"""

import re
from dataclasses import dataclass, field

from congress_collector.parsers.amounts import parse_amount_range
from congress_collector.parsers.house_ptr import (
    _OWNER_CODES,
    _TICKER_ONLY_RE,
    _TICKER_TYPE_RE,
    _TYPE_ONLY_RE,
    Word,
    _group_lines,
)

_COLUMN_MARGIN = 3.0
_SCHEDULE_RE = re.compile(r"^schedule$", re.IGNORECASE)
_ANNOTATION_RE = re.compile(r"^(description|location|subholding|comments|filing)\b", re.IGNORECASE)
_SINGLE_VALUE_WORDS = {"none", "undetermined"}
_RANGE_START_RE = re.compile(r"^\$[\d,]+$")


@dataclass(frozen=True)
class ParsedHolding:
    row_index: int
    owner: str
    asset_description_raw: str
    ticker: str | None
    asset_type: str | None
    value_raw: str
    value_min: float | None
    value_max: float | None
    income_type: str | None
    income_raw: str | None


@dataclass(frozen=True)
class _Columns:
    owner_x: float
    value_x: float
    income_type_x: float
    income_x: float
    tx_x: float


@dataclass
class _Row:
    asset: list[str] = field(default_factory=list)
    owner: str | None = None
    value: list[str] = field(default_factory=list)
    income_type: list[str] = field(default_factory=list)
    income: list[str] = field(default_factory=list)

    def value_open(self) -> bool:
        """True while a value band wraps: "$100,001 -" awaits "$250,000"."""
        return bool(self.value) and self.value[-1].endswith("-")

    def finalize(self, row_index: int) -> ParsedHolding:
        description = " ".join(self.asset).strip()
        ticker = asset_type = None
        match = _TICKER_TYPE_RE.search(description)
        if match:
            ticker, asset_type = match.group(1).upper(), match.group(2).upper()
        elif type_match := _TYPE_ONLY_RE.search(description):
            asset_type = type_match.group(1).upper()
        elif ticker_match := _TICKER_ONLY_RE.search(description):
            ticker = ticker_match.group(1).upper()
        value_raw = " ".join(self.value).strip()
        value_min, value_max = parse_amount_range(value_raw)
        return ParsedHolding(
            row_index=row_index,
            owner=_OWNER_CODES.get(self.owner or "", "self"),
            asset_description_raw=description,
            ticker=ticker,
            asset_type=asset_type,
            value_raw=value_raw,
            value_min=value_min,
            value_max=value_max,
            income_type=" ".join(self.income_type).strip() or None,
            income_raw=" ".join(self.income).strip() or None,
        )


def _line_text(line: list[Word]) -> str:
    return " ".join(w.text for w in line)


def _schedule_letter(line: list[Word]) -> str | None:
    """'a', 'b', ... if this line is a "Schedule X:" section heading.

    Pre-2022 reports write the heading as plain scrambled-case text
    ("ScHeDule a:"); 2022+ reports render it the way they render annotation
    labels, first letter plus NUL bytes ("S\x00\x00\x00\x00\x00\x00\x00 A:"),
    confirmed on DocID 10067213 (2024)."""
    if len(line) < 2 or not line[1].text.endswith(":"):
        return None
    first = line[0].text
    if _SCHEDULE_RE.match(first) or (
        first[:1] in "Ss" and first[1:] and set(first[1:]) == {"\x00"}
    ):
        return line[1].text.rstrip(":").lower()
    return None


def _header_columns(line: list[Word]) -> _Columns | None:
    """Column x0s from Schedule A's header row, or None if `line` isn't it."""
    words = [w.text.lower() for w in line]
    if not words or words[0] != "asset" or "owner" not in words or "value" not in words:
        return None
    pos: dict[str, float] = {}
    for w in line:
        pos.setdefault(w.text.lower(), w.x0)
    incomes = [w.x0 for w in line if w.text.lower() == "income"]
    if "tx." not in pos or len(incomes) < 2:
        return None
    return _Columns(
        owner_x=pos["owner"] - _COLUMN_MARGIN,
        value_x=pos["value"] - _COLUMN_MARGIN,
        income_type_x=incomes[0] - _COLUMN_MARGIN,
        income_x=incomes[1] - _COLUMN_MARGIN,
        tx_x=pos["tx."] - _COLUMN_MARGIN,
    )


def is_electronic_fd(pages_words: list[list[Word]]) -> bool:
    """True if the report has a text layer with Schedule A's header row."""
    return any(
        _header_columns(line) is not None for words in pages_words for line in _group_lines(words)
    )


def _starts_value(words: list[Word]) -> bool:
    """True if the value-zone words open a new value (not finish a wrapped one)."""
    if not words:
        return False
    first = words[0].text
    if first.lower() in _SINGLE_VALUE_WORDS or first.lower() in {"over", "spouse/dc"}:
        return True
    # "$100,001 -" opens a band; a lone "$250,000" closes a wrapped one.
    return bool(_RANGE_START_RE.match(first)) and len(words) > 1 and words[1].text == "-"


def parse_schedule_a(pages_words: list[list[Word]]) -> list[ParsedHolding]:
    holdings: list[ParsedHolding] = []
    cols: _Columns | None = None
    in_a = False
    in_annotation = False
    current: _Row | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and (current.asset or current.value):
            holdings.append(current.finalize(len(holdings)))
        current = None

    for words in pages_words:
        for line in _group_lines(words):
            letter = _schedule_letter(line)
            if letter is not None:
                if in_a and letter != "a":
                    flush()
                    return holdings
                in_a = letter == "a"
                continue
            if not in_a:
                continue
            header = _header_columns(line)
            if header is not None:
                cols = header
                continue
            text = _line_text(line)
            if cols is None or text.lower().startswith(("type(s)", "http")) or text.startswith("*"):
                continue  # second header line, or a footnote ("* For the complete list ...")
            if "\x00" in line[0].text or _ANNOTATION_RE.match(line[0].text):
                # plain ("DESCRIPTION:") or 2022+ NUL-padded label ("D\x00...:",
                # "C\x00...:" for Comments) -- every NUL-padded word on the
                # form is a label
                in_annotation = True
                continue

            asset = [w for w in line if w.x0 < cols.owner_x]
            owner = [w for w in line if cols.owner_x <= w.x0 < cols.value_x]
            value = [w for w in line if cols.value_x <= w.x0 < cols.income_type_x]
            income_type = [w for w in line if cols.income_type_x <= w.x0 < cols.income_x]
            income = [w for w in line if cols.income_x <= w.x0 < cols.tx_x]
            if not (asset or owner or value or income_type or income):
                continue  # only checkbox glyphs in the tx. > $1,000? column

            # A row's first line always carries its value, and often an
            # owner code; wrapped description and value lines never open a
            # value band. A long annotation wraps across every column, so
            # inside one only a new value band ends it.
            owner_code = bool(owner) and owner[0].text.upper() in _OWNER_CODES
            opens_value = _starts_value(value) and (current is None or not current.value_open())
            new_row = current is None or opens_value or (owner_code and not in_annotation)
            if new_row:
                flush()
                current = _Row()
                in_annotation = False
            elif in_annotation:
                continue
            assert current is not None
            current.asset += [w.text for w in asset]
            if owner_code:
                current.owner = owner[0].text.upper()
            current.value += [w.text for w in value]
            current.income_type += [w.text for w in income_type]
            current.income += [w.text for w in income]
    flush()
    return holdings


def report_year(pages_words: list[list[Word]]) -> int | None:
    """The calendar year the report covers ("Filing Year: 2020"), whose
    holdings are as of its year end."""
    for words in pages_words[:1]:
        for line in _group_lines(words):
            texts = [w.text.lower() for w in line]
            if texts[:2] == ["filing", "year:"] and len(texts) > 2 and texts[2].isdigit():
                return int(texts[2])
    return None


def has_schedule_a(pages_words: list[list[Word]]) -> bool:
    """True if the report has a text layer with a Schedule A heading, even
    one that reads "None disclosed." (no header row, no holdings)."""
    return any(
        _schedule_letter(line) == "a" for words in pages_words for line in _group_lines(words)
    )
