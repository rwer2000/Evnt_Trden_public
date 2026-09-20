"""Parse an electronic Senate PTR HTML page into structured transactions.

Table structure confirmed live from a GitHub Actions runner (this
sandbox's egress proxy blocks the domain): a plain, well-formed HTML
`<table>` with header row `['#', 'Transaction Date', 'Owner', 'Ticker',
'Asset Name', 'Asset Type', 'Type', 'Amount', 'Comment']`. Unlike House's
PDFs, no garbled text or positional reconstruction is needed -- a
straight table parse works.

Option transactions embed their details directly in the Asset Name cell
("Option Type: Call Strike price:$75.00 Expires:2026-08-21"); that gets
parsed out into `option_type`/`strike`/`expiry` and stripped from the
asset description rather than left duplicated in both places.

The site doesn't expose a per-transaction notification date (only the
filing-level submitted date, already recorded on `filings`), so
`notification_date` is always None here.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

from selectolax.parser import HTMLParser

from congress_collector.parsers.amounts import parse_amount_range, to_number

_OWNER_CODES = {
    "self": "self",
    "spouse": "spouse",
    "joint": "joint",
    "dependent child": "child",
}
_TX_TYPE_CODES = {
    "purchase": "purchase",
    "sale (full)": "sale_full",
    "sale (partial)": "sale_partial",
    "exchange": "exchange",
}

_OPTION_RE = re.compile(
    r"Option Type:\s*(?P<type>Call|Put)\s*"
    r"Strike price:\s*\$(?P<strike>[\d,.]+)\s*"
    r"Expires:\s*(?P<expiry>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTransaction:
    row_index: int
    owner: str | None
    asset_description_raw: str
    ticker: str | None
    asset_type: str | None
    option_type: str | None
    strike: float | None
    expiry: date | None
    tx_type: str | None
    tx_date: date | None
    amount_min: float | None
    amount_max: float | None


def parse_ptr_html(html: str) -> list[ParsedTransaction]:
    root = HTMLParser(html)
    table = root.css_first("table")
    if table is None:
        return []

    results = []
    for row_index, tr in enumerate(table.css("tbody tr")):
        cells = [td.text(separator=" ", strip=True) for td in tr.css("td")]
        if len(cells) < 9:
            continue
        (
            _,
            tx_date_raw,
            owner_raw,
            ticker_raw,
            asset_name_raw,
            asset_type_raw,
            tx_type_raw,
            amount_raw,
            _comment,
        ) = cells[:9]

        option_type, strike, expiry = _extract_option_details(asset_name_raw)
        amount_min, amount_max = parse_amount_range(amount_raw)

        results.append(
            ParsedTransaction(
                row_index=row_index,
                owner=_OWNER_CODES.get(owner_raw.strip().lower()),
                asset_description_raw=_strip_option_details(asset_name_raw),
                ticker=_clean_dash(ticker_raw),
                asset_type=_clean_dash(asset_type_raw),
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                tx_type=_TX_TYPE_CODES.get(tx_type_raw.strip().lower()),
                tx_date=_parse_date(tx_date_raw),
                amount_min=amount_min,
                amount_max=amount_max,
            )
        )
    return results


def _extract_option_details(asset_name: str) -> tuple[str | None, float | None, date | None]:
    match = _OPTION_RE.search(asset_name)
    if not match:
        return None, None, None
    return (
        match.group("type").lower(),
        to_number(match.group("strike")),
        date.fromisoformat(match.group("expiry")),
    )


def _strip_option_details(asset_name: str) -> str:
    idx = asset_name.find("Option Type:")
    return (asset_name[:idx] if idx != -1 else asset_name).strip()


def _clean_dash(raw: str) -> str | None:
    value = raw.strip()
    return value if value and value != "--" else None


def _parse_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None
    return datetime.strptime(value, "%m/%d/%Y").date()
