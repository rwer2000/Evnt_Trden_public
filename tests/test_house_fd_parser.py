"""Tests for the House annual report (Schedule A) parser, on real public
House Clerk PDFs in tests/fixtures/house_fd/:

- 10022048: 2017 report, scrambled-case text layer, sub-holdings written
  "Account ⇒" / held asset, tickered mutual funds and a stock.
- 10053011: 2022 report, NUL-padded "S...: A:" headings and annotation
  labels, plain-case stocks.
- 10067213: 2024 report whose Schedule A reads "None disclosed."
"""

from pathlib import Path

import pytest

from congress_collector.parsers.house_fd import (
    _Row,
    has_schedule_a,
    is_electronic_fd,
    parse_schedule_a,
    report_year,
)
from congress_collector.parsers.house_ptr import Word, extract_pages_words

_FIXTURES = Path(__file__).parent / "fixtures" / "house_fd"


def _pages(doc_id: str) -> list[list[Word]]:
    return extract_pages_words((_FIXTURES / f"{doc_id}.pdf").read_bytes())


def test_scrambled_case_report_with_sub_holdings() -> None:
    pages = _pages("10022048")
    assert is_electronic_fd(pages) and has_schedule_a(pages)
    assert report_year(pages) == 2017
    holdings = parse_schedule_a(pages)
    assert len(holdings) == 15
    first = holdings[0]
    assert first.asset_description_raw.startswith("aF IRa ⇒ CaPITaL INCOME BUILDER")
    assert (first.ticker, first.asset_type, first.owner) == ("CAIBX", "MF", "self")
    assert (first.value_min, first.value_max) == (50001.0, 100000.0)
    stock = holdings[10]
    assert (stock.ticker, stock.asset_type) == ("USB", "ST")
    assert (stock.income_type, stock.income_raw) == ("Dividends", "$1 - $200")
    assert [h.row_index for h in holdings] == list(range(15))


def test_nul_padded_2022_report() -> None:
    pages = _pages("10053011")
    assert report_year(pages) == 2022
    holdings = parse_schedule_a(pages)
    assert len(holdings) == 35
    by_ticker = {h.ticker: h for h in holdings if h.ticker}
    assert set(by_ticker) >= {"AMZN", "AAPL", "JNJ", "MSFT", "PG"}
    assert (by_ticker["AAPL"].value_min, by_ticker["AAPL"].value_max) == (500001.0, 1000000.0)
    assert all("\x00" not in h.asset_description_raw for h in holdings)


def test_none_disclosed_report_has_schedule_a_but_no_holdings() -> None:
    pages = _pages("10067213")
    assert has_schedule_a(pages)
    assert not is_electronic_fd(pages)  # no header row: nothing is listed
    assert parse_schedule_a(pages) == []
    assert report_year(pages) == 2024


def test_scanned_report_without_text_is_not_electronic() -> None:
    assert not is_electronic_fd([[]])
    assert not has_schedule_a([[]])


def _ticker_and_type(description: str) -> tuple[str | None, str | None]:
    holding = _Row(asset=[description], value=["None"]).finalize(0)
    return holding.ticker, holding.asset_type


# Descriptions as they appear on real reports (congress.holdings, 2026-10-11).
@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # an asset-type code in the ticker's parentheses is a label, not a ticker
        ("Morgan Stanley Trad. IRA ⇒ Berkshire Hathaway CL B New (MF) [BA]", (None, "BA")),
        ("Dodge and Cox International Fund (MF) [MF]", (None, "MF")),
        ("Maryland Retirement Agency (PE) [PE]", (None, "PE")),
        ("Investacorp Inc. (S.E.P) (PE) [FN]", (None, "FN")),
        ("Voya Intermediate Bond Fund (EF) [PE]", (None, "PE")),
        ("IShares TR Russell Mid-Cap ETF (EF) [EF]", (None, "EF")),
        ("JPMorgan Ultra-Short Income (ETF) [EF]", (None, "EF")),
        ("CEFCU Checking and Savings (BA) [OT]", (None, "OT")),
        ("USC Retirement Savings 401(a) - Fidelity Cash Reserve (IH) [BA]", (None, "BA")),
        ("Brighthouse Life Insurance Company (FN) [FN]", (None, "FN")),
        ("Pacific Life Portfolio Moderate (mf) [mf]", (None, "MF")),  # scrambled case
        # real tickers, including ones that spell a code
        ("Apple Inc. (AAPL) [ST]", ("AAPL", "ST")),
        ("Boeing Company (BA) [ST]", ("BA", "ST")),
        ("Goldman Sachs Group, Inc. (GS) [ST]", ("GS", "ST")),
        ("Sensata Technologies Holding N.V. (ST) [ST]", ("ST", "ST")),
        ("AllianceBernstein Holding L.P. Units (AB) [OL]", ("AB", "OL")),
        ("Energy Transfer LP Common Units (ET) [AB]", ("ET", "AB")),
        ("aF IRa ⇒ CaPITaL INCOME BUILDER (CaIBX) [mF]", ("CAIBX", "MF")),
        # pre-2019 form, no bracket: nothing tells a label from a ticker
        ("Boeing Company (BA)", ("BA", None)),
        ("Fidelity Investments ⇒ SEP: FIDELITY CASH RESERVES [MF]", (None, "MF")),
    ],
)
def test_asset_type_code_in_parentheses_is_not_a_ticker(
    description: str, expected: tuple[str | None, str | None]
) -> None:
    assert _ticker_and_type(description) == expected
