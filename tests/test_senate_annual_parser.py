"""Tests for the Senate annual report (Part 3, Assets) parser, on real
public eFD report pages in tests/fixtures/senate_annual/ (fetched from
efdsearch.senate.gov on 2026-10-11):

- 0ced71f1: Schiff, CY 2025 -- IRAs and a brokerage account with tickered
  sub-holdings ("2.1"), a bank sweep account with location/type details.
- d4f1a4cf: Tuberville, CY 2025 -- 44 stocks, "Unascertainable" pensions,
  an exact "Other $47,071.32" income amount, "None (or less than $1,001)".
- fe9962a4: Booker, CY 2013 -- the oldest electronic format, flat rows.
- 10b18219: Wyden, CY 2017 -- dependent-child 529 plans, "Description:"
  details.
- 3efd1613: Budd, 2022 candidate report -- no calendar year.
"""

import urllib.parse
from datetime import date
from pathlib import Path

import httpx
import pytest

from congress_collector.parsers.senate_annual import has_assets_part, parse_assets, report_year
from congress_collector.sources.senate_annual import (
    fetch_annual_index,
    fetch_annual_report,
    parse_annual_rows,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "senate_annual"


def _html(report_uuid: str) -> str:
    return (_FIXTURES / f"{report_uuid}.html").read_text(encoding="utf-8")


def test_sub_holdings_are_prefixed_with_their_account_and_accounts_dropped() -> None:
    html = _html("0ced71f1-1a11-48aa-87da-f6ed733836b8")
    assert report_year(html) == 2025 and has_assets_part(html)
    holdings = parse_assets(html)
    # 19 table rows, 5 of them accounts ("--" value) whose value sits on sub-rows.
    assert len(holdings) == 14
    assert [h.row_index for h in holdings] == list(range(14))
    apple = holdings[1]
    assert apple.item_number == "2.1"
    assert apple.asset_description_raw == "UBS Brokerage Account ⇒ AAPL - Apple Inc"
    assert (apple.ticker, apple.asset_type, apple.asset_type_raw) == (
        "AAPL",
        "ST",
        "Corporate Securities: Stock",
    )
    assert apple.owner == "spouse"
    assert (apple.value_min, apple.value_max) == (100001.0, 250000.0)
    assert (apple.income_type, apple.income_raw) == (
        "Dividends, Capital Gains",
        "$15,001 - $50,000",
    )
    sweep = holdings[4]
    assert sweep.ticker is None and sweep.asset_type == "BA"
    assert sweep.details == "(Washington, DC) Type: Brokerage Sweep Account"
    annuity = holdings[-1]
    assert (annuity.item_number, annuity.asset_type) == ("6", "Annuity: Fixed")


def test_unascertainable_values_and_exact_other_income() -> None:
    holdings = parse_assets(_html("d4f1a4cf-d450-4f9f-bfaf-c98e41066c2b"))
    assert len(holdings) == 82
    assert sum(h.asset_type == "ST" for h in holdings) == 44
    assert {h.owner for h in holdings} == {"self", "joint"}
    pension = holdings[77]
    assert pension.asset_description_raw == "Alabama Pension"
    assert pension.value_raw == "Unascertainable"
    assert (pension.value_min, pension.value_max) == (None, None)
    assert pension.income_raw == "Other $47,071.32"
    small = next(h for h in holdings if h.value_raw == "None (or less than $1,001)")
    assert (small.value_min, small.value_max) == (0.0, 1000.0)


def test_oldest_electronic_format_cy_2013() -> None:
    html = _html("fe9962a4-8d3d-4643-bf6a-03030d0a9fba")
    assert report_year(html) == 2013
    holdings = parse_assets(html)
    assert len(holdings) == 20
    first = holdings[0]
    assert (first.ticker, first.asset_type, first.owner) == ("AMZN", "ST", "self")
    assert first.asset_description_raw == "AMZN - Amazon.com Inc. (NASDAQ)"


def test_dependent_child_owner_and_unmapped_asset_type() -> None:
    holdings = parse_assets(_html("10b18219-85da-4e14-954d-514f4ea3300e"))
    assert len(holdings) == 42
    children = [h for h in holdings if h.owner == "child"]
    assert len(children) == 2
    assert children[0].asset_type == "Education Savings Plans: 529 Prepaid Tuition"
    assert children[0].details == "Institution: Oregon"


def test_candidate_report_has_no_calendar_year() -> None:
    html = _html("3efd1613-f4b4-45c7-9a72-6308f6f63d12")
    assert report_year(html) is None
    assert len(parse_assets(html)) == 84


def test_multi_part_income_cell_and_missing_part_3() -> None:
    html = """
    <section><h3>Part 3. Assets</h3><table><tbody><tr>
      <td>1</td><td><strong>Family LLC</strong><div class="muted"></div></td>
      <td>Business Entity<div class="muted">Limited Liability Company (LLC)</div></td>
      <td>Self</td><td>Over $50,000,000</td><td>Interest, Other (Ordinary Income)</td>
      <td>None (or less than $201)<br/>Other $50,001.00</td>
    </tr></tbody></table></section>
    """
    (holding,) = parse_assets(html)
    assert holding.income_raw == "None (or less than $201); Other $50,001.00"
    assert (holding.value_min, holding.value_max) == (50000000.0, None)
    assert holding.asset_type == "Business Entity: Limited Liability Company (LLC)"
    assert not has_assets_part("<section><h3>Part 2. Earned</h3></section>")
    assert parse_assets("<section><h3>Part 2. Earned</h3></section>") == []


def test_parse_annual_rows_kinds() -> None:
    # Real result rows from a live report_type=7 search (2026-10-11).
    rows = [
        [
            "Tim",
            "Scott",
            "Scott, Tim (Senator)",
            '<a href="/search/view/annual/c6b1e74d-4cc1-4411-bb78-b22e8fa01e8e/" '
            'target="_blank">Annual Report for CY 2025 (Amendment 1)</a>',
            "10/06/2026",
        ],
        [
            "Darline",
            "Graham",
            "Graham, Darline (Senator)",
            '<a href="/search/view/annual/3f5f8a40-87d9-4e6c-ba86-7f65faa0dd47/" '
            'target="_blank">New Filer Report for 07/14/2026</a>',
            "08/07/2026",
        ],
        [
            "THEODORE P",
            "BUDD",
            "Candidate (Candidate)",
            '<a href="/search/view/annual/3efd1613-f4b4-45c7-9a72-6308f6f63d12/" '
            'target="_blank">Candidate Report </a>',
            "08/12/2022",
        ],
        [
            "ELIZABETH ",
            "WARREN",
            "Senator",
            '<a href="/search/view/paper/77234B85-2803-4E3D-938F-E51E03F7AF54/" '
            'target="_blank">Annual Report (Amendment)</a>',
            "02/06/2013",
        ],
    ]
    amended, new_filer, candidate, paper = parse_annual_rows(rows)
    assert (amended.kind, amended.calendar_year, amended.amendment) == ("annual", 2025, 1)
    assert amended.is_electronic
    assert (new_filer.kind, new_filer.calendar_year, new_filer.amendment) == (
        "new_filer",
        None,
        None,
    )
    assert candidate.kind == "candidate" and candidate.title == "Candidate Report"
    assert (paper.kind, paper.amendment, paper.is_electronic) == ("paper", 0, False)
    assert paper.report_uuid == "77234b85-2803-4e3d-938f-e51e03f7af54"
    assert paper.last_name == "WARREN"


def test_fetch_annual_index_asks_for_report_type_7_and_paginates() -> None:
    row = [
        "Tim",
        "Scott",
        "Scott, Tim (Senator)",
        '<a href="/search/view/annual/c6b1e74d-4cc1-4411-bb78-b22e8fa01e8e/" '
        'target="_blank">Annual Report for CY 2025</a>',
        "10/06/2026",
    ]
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        seen.append(form)
        count = 2 if form["start"] == ["0"] else 1
        return httpx.Response(200, json={"result": "ok", "data": [row] * count})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries = fetch_annual_index(client, submitted_start=date(2025, 1, 1), page_size=2)

    assert len(entries) == 3
    assert [f["report_types"] for f in seen] == [["[7]"], ["[7]"]]
    assert [f["start"] for f in seen] == [["0"], ["2"]]


def test_fetch_annual_report_rejects_a_redirect_to_the_agreement_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/search/view/"):
            return httpx.Response(302, headers={"Location": "/search/home/"})
        return httpx.Response(200, text="agreement")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    with pytest.raises(RuntimeError):
        fetch_annual_report(client, "c6b1e74d-4cc1-4411-bb78-b22e8fa01e8e")
