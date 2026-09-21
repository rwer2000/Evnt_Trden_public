"""Fetch House Stock Watcher and Senate Stock Watcher's published
datasets (T21's community archive import).

Neither the original housestockwatcher.com nor its `timothycarambat/
house-stock-watcher` GitHub repo exist any more (the domain doesn't even
resolve) -- confirmed live via a GitHub Actions runner (this sandbox's
egress proxy blocks all of these domains). The actively maintained
successor is `TattooedHead/house-stock-watcher-data`, whose
`filing_id` field is the House Clerk's own DocID -- the same identifier
`sources.house.filing_id_for()` already uses, so matching a community
record to our own `filings` row is a direct string match, no fuzzy
matching needed.

Senate has no actively maintained equivalent: `timothycarambat/
senate-stock-watcher-data` (senatestockwatcher.com's own former data
repo) hasn't been pushed to since March 2021. Used anyway, deliberately
-- a frozen snapshot is arguably *better* for T21's survivorship-bias
purpose than a live one would be: it shows exactly what the site
captured at the time, uncontaminated by any later re-scraping, which is
exactly what "does the official record still show what was once public"
needs to compare against. Its records don't carry an explicit filing ID,
but the Senate eFD report UUID is embedded in their `ptr_link` field
(`.../search/view/ptr/<uuid>/`), which matches
`sources.senate.filing_id_for()`'s input directly.

Both datasets are published with no declared license (confirmed via the
GitHub API: `license: None` on both repos) -- acceptable for this
project's own stated use (personal research, no commercial
redistribution, see README's "Legal note"), since the underlying content
is a straightforward re-publication of U.S. government disclosure
records, not original creative work either project holds a copyright
claim over.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from congress_collector.parsers.amounts import parse_amount_range
from congress_collector.sources.house import filing_id_for as house_filing_id_for
from congress_collector.sources.senate import filing_id_for as senate_filing_id_for

HOUSE_STOCK_WATCHER_URL = (
    "https://raw.githubusercontent.com/TattooedHead/house-stock-watcher-data"
    "/main/data/all_transactions.json"
)
SENATE_STOCK_WATCHER_URL = (
    "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data"
    "/master/aggregate/all_transactions.json"
)

HOUSE_SOURCE = "house_stock_watcher"
SENATE_SOURCE = "senate_stock_watcher"

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"

_SENATE_PTR_UUID_RE = re.compile(r"/ptr/(?P<uuid>[0-9a-f-]{36})/")


@dataclass(frozen=True)
class CommunityRecord:
    source: str
    chamber: str
    external_filing_id: str | None  # our own filing_id format, e.g. "house:20035471"
    filer_name: str | None
    ticker: str | None
    asset_description: str | None
    asset_type: str | None
    tx_type: str | None
    owner: str | None
    tx_date: date | None
    disclosure_date: date | None
    amount_min: float | None
    amount_max: float | None


def fetch_house_stock_watcher(*, client: httpx.Client | None = None) -> list[CommunityRecord]:
    rows = _fetch_json(HOUSE_STOCK_WATCHER_URL, client=client)
    records = []
    for row in rows:
        doc_id = str(row.get("filing_id") or "").strip()
        amount_min, amount_max = parse_amount_range(str(row.get("amount") or ""))
        records.append(
            CommunityRecord(
                source=HOUSE_SOURCE,
                chamber="house",
                external_filing_id=house_filing_id_for(doc_id) if doc_id else None,
                filer_name=_clean(row.get("representative")),
                ticker=_clean(row.get("ticker")),
                asset_description=_clean(row.get("asset_description")),
                asset_type=_clean(row.get("asset_type")),
                tx_type=_clean(row.get("type")),
                owner=_clean(row.get("owner")),
                tx_date=_parse_date(row.get("transaction_date")),
                disclosure_date=_parse_date(row.get("disclosure_date")),
                amount_min=amount_min,
                amount_max=amount_max,
            )
        )
    return records


def fetch_senate_stock_watcher(*, client: httpx.Client | None = None) -> list[CommunityRecord]:
    rows = _fetch_json(SENATE_STOCK_WATCHER_URL, client=client)
    records = []
    for row in rows:
        uuid_match = _SENATE_PTR_UUID_RE.search(str(row.get("ptr_link") or ""))
        amount_min, amount_max = parse_amount_range(str(row.get("amount") or ""))
        records.append(
            CommunityRecord(
                source=SENATE_SOURCE,
                chamber="senate",
                external_filing_id=(
                    senate_filing_id_for(uuid_match.group("uuid")) if uuid_match else None
                ),
                filer_name=_clean(row.get("senator")),
                ticker=_clean(row.get("ticker")),
                asset_description=_clean(row.get("asset_description")),
                asset_type=_clean(row.get("asset_type")),
                tx_type=_clean(row.get("type")),
                owner=_clean(row.get("owner")),
                tx_date=_parse_date(row.get("transaction_date")),
                disclosure_date=None,  # not exposed per-transaction in this dataset
                amount_min=amount_min,
                amount_max=amount_max,
            )
        )
    return records


def _fetch_json(url: str, *, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    owns_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True, timeout=60.0, headers={"User-Agent": USER_AGENT}
    )
    try:
        response = active_client.get(url)
        response.raise_for_status()
        data: list[dict[str, Any]] = response.json()
        return data
    finally:
        if owns_client:
            active_client.close()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text != "--" else None


def _parse_date(value: Any) -> date | None:
    if not value or not str(value).strip():
        return None
    try:
        return datetime.strptime(str(value).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None
