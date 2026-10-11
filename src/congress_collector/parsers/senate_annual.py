"""Parse Part 3 ("Assets") of an electronic Senate annual report into
holdings -- the Senate counterpart of ``parsers.house_fd``.

Page structure confirmed live (2026-10-11, fetched from this sandbox) on
reports for CY 2013, 2017 and 2025, a candidate report and a new-filer
report: every electronic report under ``/search/view/annual/<uuid>/`` is
one HTML page with a ``<section>`` per part, each headed by an ``<h3>``
("Part 3. Assets"). Part 3 holds a plain ``<table>`` with the header
``['', 'Asset', 'Asset Type', 'Owner', 'Value', 'Income Type', 'Income']``;
the layout did not change between 2014 and 2026. Shapes handled:

- the first cell numbers the row: "2" is a top-level asset, "2.1" one held
  inside asset 2 (a brokerage account or IRA). The account row itself has
  value "--" -- its value is spread over its sub-rows -- so an account row
  with sub-rows is not a holding of its own, and each sub-row's
  description is prefixed "Account ⇒ ", the way House's parser writes
  sub-holdings;
- the Asset cell's ``<strong>`` reads "TICKER - Name" with the ticker as a
  link to finance.yahoo.com when the filer picked a listed security, or
  just a name otherwise; extra lines in ``div.muted`` ("(Washington, DC)",
  "Type: Money Market Account", "Description: ...") are kept separately as
  ``details``;
- the Asset Type cell is a category plus an optional sub-type in
  ``div.muted`` ("Corporate Securities" / "Stock"). It is kept as
  "Category: Sub-type" in ``asset_type_raw`` and, where the meaning is
  unambiguous, also mapped to the House form's two-letter code
  (``asset_type``: ST, EF, MF, ...), so cross-chamber queries on
  ``holdings.asset_type`` work; an unmapped type keeps the raw label;
- value bands are the standard ones; "None (or less than $1,001)" becomes
  0-1,000 and "Unascertainable" or "--" no band;
- the Income cell can hold two parts separated by ``<br/>`` ("None (or
  less than $201)" / "Other $50,001.00"), joined with "; ".

A paper report (``/search/view/paper/<uuid>/``) is a set of scanned GIF
page images with no text, and is never passed here.
"""

import re
from dataclasses import dataclass

from selectolax.parser import HTMLParser, Node

from congress_collector.parsers.amounts import parse_amount_range

_OWNER_CODES = {
    "self": "self",
    "spouse": "spouse",
    "joint": "joint",
    "dependent child": "child",
    "child": "child",
}

# Senate "Category: Sub-type" -> House Schedule A asset-type code, only
# where the two forms clearly mean the same thing.
_HOUSE_TYPE_CODES = {
    "Corporate Securities: Stock": "ST",
    "Corporate Securities: Stock Option": "OP",
    "Mutual Funds: Mutual Fund": "MF",
    "Mutual Funds: Exchange Traded Fund/Note": "EF",
    "Government Securities: US Treasury/Agency Security": "GS",
    "Government Securities: Municipal Security": "GS",
    "Bank Deposit": "BA",
    "Investment Fund: Hedge Fund": "HE",
    "Investment Fund: Private Equity Fund": "PE",
    "Cryptocurrency": "CT",
}

_ROW_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)*$")
_TICKER_NAME_RE = re.compile(r"^(?P<ticker>[A-Z][A-Z0-9.\-/]{0,9})\s+-\s+(?P<name>.+)$")
_YEAR_RE = re.compile(r"^Annual Report for Calendar (\d{4})$")
_NO_VALUE = {"", "--", "unascertainable"}


@dataclass(frozen=True)
class ParsedSenateHolding:
    row_index: int
    item_number: str
    owner: str | None
    asset_description_raw: str
    ticker: str | None
    asset_type: str | None
    asset_type_raw: str | None
    details: str | None
    value_raw: str | None
    value_min: float | None
    value_max: float | None
    income_type: str | None
    income_raw: str | None


@dataclass(frozen=True)
class _RawRow:
    number: str
    name: str
    ticker: str | None
    details: str | None
    asset_type_raw: str | None
    owner_raw: str
    value_raw: str
    income_type: str | None
    income_raw: str | None


def report_year(html: str) -> int | None:
    """The calendar year an annual report covers ("Annual Report for
    Calendar 2025"), or None for a candidate / new-filer report, which
    cover a point in time rather than a calendar year."""
    heading = HTMLParser(html).css_first("h1")
    match = _YEAR_RE.match(_squash(heading.text(separator=" "))) if heading else None
    return int(match.group(1)) if match else None


def has_assets_part(html: str) -> bool:
    return _assets_section(HTMLParser(html)) is not None


def parse_assets(html: str) -> list[ParsedSenateHolding]:
    """Part 3's holdings, in page order. Empty when the filer answered
    "No" (no table) or when there is no Part 3 at all -- use
    ``has_assets_part`` to tell those apart."""
    section = _assets_section(HTMLParser(html))
    if section is None:
        return []
    table = section.css_first("table")
    if table is None:
        return []

    rows = [row for tr in table.css("tbody tr") if (row := _raw_row(tr)) is not None]
    names = {row.number: row.name for row in rows}
    parents = {row.number.rsplit(".", 1)[0] for row in rows if "." in row.number}

    holdings: list[ParsedSenateHolding] = []
    for row in rows:
        if row.number in parents and row.value_raw.strip() in _NO_VALUE:
            continue
        holdings.append(_to_holding(row, len(holdings), names))
    return holdings


def _assets_section(root: HTMLParser) -> Node | None:
    for section in root.css("section"):
        heading = section.css_first("h3")
        if heading is not None and heading.text(strip=True).startswith("Part 3."):
            return section
    return None


def _raw_row(tr: Node) -> _RawRow | None:
    cells = tr.css("td")
    if len(cells) < 7:
        return None
    number = cells[0].text(strip=True)
    if not _ROW_NUMBER_RE.match(number):
        return None

    asset_cell = cells[1]
    strong = asset_cell.css_first("strong")
    title = _squash(strong.text(separator=" ") if strong else asset_cell.text(separator=" "))
    ticker = None
    link = strong.css_first("a") if strong else None
    if link is not None:
        match = _TICKER_NAME_RE.match(title)
        if match:
            ticker = match.group("ticker")
    details = " ".join(
        text
        for div in asset_cell.css("div.muted")
        if not any(child.tag == "div" for child in div.iter())
        and (text := _squash(div.text(separator=" ")))
    )

    return _RawRow(
        number=number,
        name=title,
        ticker=ticker,
        details=details or None,
        asset_type_raw=_asset_type(cells[2]),
        owner_raw=cells[3].text(strip=True),
        value_raw=_squash(cells[4].text(separator=" ")),
        income_type=_squash(cells[5].text(separator=" ")) or None,
        income_raw="; ".join(_lines(cells[6])) or None,
    )


def _to_holding(row: _RawRow, row_index: int, names: dict[str, str]) -> ParsedSenateHolding:
    description = row.name
    number = row.number
    while "." in number:
        number = number.rsplit(".", 1)[0]
        if number in names:
            description = f"{names[number]} ⇒ {description}"
    value_min, value_max = _value_band(row.value_raw)
    return ParsedSenateHolding(
        row_index=row_index,
        item_number=row.number,
        owner=_OWNER_CODES.get(row.owner_raw.lower()),
        asset_description_raw=description,
        ticker=row.ticker,
        asset_type=_HOUSE_TYPE_CODES.get(row.asset_type_raw or "", row.asset_type_raw),
        asset_type_raw=row.asset_type_raw,
        details=row.details,
        value_raw=None if row.value_raw.strip() in ("", "--") else row.value_raw,
        value_min=value_min,
        value_max=value_max,
        income_type=row.income_type,
        income_raw=row.income_raw,
    )


def _value_band(raw: str) -> tuple[float | None, float | None]:
    value = raw.strip()
    if value.lower() in _NO_VALUE:
        return None, None
    if value.lower().startswith("none (or less than"):
        return 0.0, 1000.0
    return parse_amount_range(value)


def _asset_type(cell: Node) -> str | None:
    """ "Category: Sub-type" -- the cell's text is the category followed by
    the sub-type's ``div.muted``."""
    full = _squash(cell.text(separator=" "))
    sub = cell.css_first("div.muted")
    sub_type = _squash(sub.text(separator=" ")) if sub is not None else ""
    if sub_type and full.endswith(sub_type):
        category = full[: -len(sub_type)].strip()
        return f"{category}: {sub_type}" if category else sub_type
    return full or None


def _lines(cell: Node) -> list[str]:
    html = cell.html or ""
    parts = re.split(r"<br\s*/?>", html)
    return [text for part in parts if (text := _squash(HTMLParser(part).text(separator=" ")))]


def _squash(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())
