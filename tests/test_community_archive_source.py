from datetime import date

import httpx

from congress_collector.sources.community_archive import (
    fetch_house_stock_watcher,
    fetch_senate_stock_watcher,
)

_HOUSE_ROW = {
    "transaction_date": "09/08/2026",
    "disclosure_date": "09/17/2026",
    "ticker": "PG",
    "asset_description": "Procter & Gamble Company",
    "asset_type": "Stock",
    "type": "Purchase",
    "amount": "$1,001 - $15,000",
    "amount_mid": 8000,
    "representative": "David J. Taylor",
    "district": "OH02",
    "owner": "Self",
    "filing_id": "20035471",
    "source_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035471.pdf",
}

_HOUSE_ROW_NO_FILING_ID = {**_HOUSE_ROW, "filing_id": ""}

_SENATE_ROW = {
    "transaction_date": "11/10/2020",
    "owner": "Spouse",
    "ticker": "BYND",
    "asset_description": "Beyond Meat, Inc.",
    "asset_type": "Stock",
    "type": "Sale (Full)",
    "amount": "$50,001 - $100,000",
    "comment": "--",
    "senator": "Ron L Wyden",
    "ptr_link": "https://efdsearch.senate.gov/search/view/ptr/a0010f4a-c31a-4824-8b6d-6399b3ccb6f0/",
}

_SENATE_ROW_BAD_LINK = {**_SENATE_ROW, "ptr_link": ""}


def test_fetch_house_stock_watcher_parses_and_derives_our_filing_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_HOUSE_ROW, _HOUSE_ROW_NO_FILING_ID])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = fetch_house_stock_watcher(client=client)

    assert len(records) == 2
    first = records[0]
    assert first.source == "house_stock_watcher"
    assert first.chamber == "house"
    assert first.external_filing_id == "house:20035471"
    assert first.filer_name == "David J. Taylor"
    assert first.ticker == "PG"
    assert first.asset_description == "Procter & Gamble Company"
    assert first.tx_type == "Purchase"
    assert first.owner == "Self"
    assert first.tx_date == date(2026, 9, 8)
    assert first.disclosure_date == date(2026, 9, 17)
    assert first.amount_min == 1001
    assert first.amount_max == 15000

    assert records[1].external_filing_id is None


def test_fetch_house_stock_watcher_strips_nul_bytes_from_asset_description() -> None:
    # Confirmed live: house-stock-watcher-data's own scraper leaks raw
    # NUL-byte PTR PDF font artifacts (the "Filing Status:"/"Subholding
    # Of:" annotation-label quirk parsers.house_ptr already handles
    # carefully) straight into fields like asset_description. Postgres
    # text columns can't store NUL bytes at all -- this broke the import
    # until stripped.
    jammed = "Applied Materials - Common Stock F\x00\x00\x00 S\x00: New"
    row = {**_HOUSE_ROW, "asset_description": jammed}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[row])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = fetch_house_stock_watcher(client=client)

    assert records[0].asset_description == "Applied Materials - Common Stock F S: New"


def test_fetch_senate_stock_watcher_extracts_uuid_from_ptr_link() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_SENATE_ROW, _SENATE_ROW_BAD_LINK])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = fetch_senate_stock_watcher(client=client)

    assert len(records) == 2
    first = records[0]
    assert first.source == "senate_stock_watcher"
    assert first.chamber == "senate"
    assert first.external_filing_id == "senate:a0010f4a-c31a-4824-8b6d-6399b3ccb6f0"
    assert first.filer_name == "Ron L Wyden"
    assert first.tx_date == date(2020, 11, 10)
    assert first.disclosure_date is None
    assert first.amount_min == 50001
    assert first.amount_max == 100000

    assert records[1].external_filing_id is None
