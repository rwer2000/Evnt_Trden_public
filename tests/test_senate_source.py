import urllib.parse
from datetime import date

import httpx
import pytest

from congress_collector.sources import senate

# Real result rows from a live search for report_type=11, captured via a
# GitHub Actions runner (this sandbox's egress proxy blocks the domain).
_ELECTRONIC_ROW = [
    "Alan",
    "Armstrong",
    "Armstrong, Alan (Senator)",
    '<a href="/search/view/ptr/b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f/" '
    'target="_blank">Periodic Transaction Report for 09/17/2026</a>',
    "09/17/2026",
]
_PAPER_ROW = [
    "RICHARD ",
    "BLUMENTHAL",
    "Senator",
    '<a href="/search/view/paper/929216d5-5dbd-429c-858c-1e9332924627/" '
    'target="_blank">Periodic Transaction Report for 08/31/2026</a>',
    "08/31/2026",
]
# A filer-amended report's link text carries a "(Amendment N)" suffix --
# confirmed live during T20's backfill, where this pattern turned out to
# be ~17% of all rows on one sampled page.
_AMENDED_ROW = [
    "John",
    "Boozman",
    "Boozman, John (Senator)",
    '<a href="/search/view/ptr/51455bcd-4966-4e77-b481-09897ada81ae/" '
    'target="_blank">Periodic Transaction Report for 12/08/2025 (Amendment 1)</a>',
    "08/24/2026",
]


def test_new_session_accepts_agreement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/search/home/":
            return httpx.Response(200, headers={"Set-Cookie": "csrftoken=abc123; Path=/"})
        if request.method == "POST" and request.url.path == "/search/home/":
            assert request.headers.get("Referer") == senate.HOME_URL
            return httpx.Response(200, headers={"Set-Cookie": "sessionid=xyz; Path=/"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    session = senate.new_session(client=client)

    assert session.cookies.get("csrftoken") == "abc123"
    assert session.cookies.get("sessionid") == "xyz"


def test_new_session_raises_without_csrf_cookie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="csrftoken"):
        senate.new_session(client=client)


def test_new_session_raises_when_agreement_not_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"Set-Cookie": "csrftoken=abc123; Path=/"})
        return httpx.Response(200)  # no sessionid set

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="agreement"):
        senate.new_session(client=client)


def test_fetch_ptr_page_parses_electronic_and_paper_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/report/data/"
        return httpx.Response(
            200,
            json={"data": [_ELECTRONIC_ROW, _PAPER_ROW], "result": "ok"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), cookies={"csrftoken": "abc123"})
    entries = senate.fetch_ptr_page(client, date(2026, 1, 1), 0, 100)

    assert len(entries) == 2
    assert entries[0].report_uuid == "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    assert entries[0].is_electronic is True
    assert entries[0].filed_date == date(2026, 9, 17)
    assert entries[1].report_uuid == "929216d5-5dbd-429c-858c-1e9332924627"
    assert entries[1].is_electronic is False
    assert entries[1].first_name == "RICHARD"


def test_fetch_ptr_page_parses_amended_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [_AMENDED_ROW], "result": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler), cookies={"csrftoken": "abc123"})
    entries = senate.fetch_ptr_page(client, date(2026, 1, 1), 0, 100)

    assert len(entries) == 1
    assert entries[0].report_uuid == "51455bcd-4966-4e77-b481-09897ada81ae"
    assert entries[0].is_electronic is True
    assert entries[0].filed_date == date(2026, 8, 24)  # the amendment's own submitted date


def test_fetch_ptr_page_raises_on_error_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "error"})

    client = httpx.Client(transport=httpx.MockTransport(handler), cookies={"csrftoken": "abc"})
    with pytest.raises(RuntimeError, match="error"):
        senate.fetch_ptr_page(client, date(2026, 1, 1), 0, 100)


def test_fetch_ptr_index_paginates_until_a_short_page() -> None:
    call_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = urllib.parse.parse_qs(request.read().decode())
        start = int(params["start"][0])
        call_starts.append(start)
        rows = [_ELECTRONIC_ROW, _PAPER_ROW] if start == 0 else [_ELECTRONIC_ROW]
        return httpx.Response(200, json={"data": rows, "result": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler), cookies={"csrftoken": "abc"})
    entries = senate.fetch_ptr_index(client, submitted_start=date(2026, 1, 1), page_size=2)

    assert call_starts == [0, 2]
    assert len(entries) == 3


def test_fetch_ptr_index_keeps_paginating_past_a_page_with_unparseable_rows() -> None:
    # A full page whose rows don't all match _LINK_RE (e.g. amendments,
    # before that regex was fixed) must not look like a short/last page --
    # confirmed live that this silently truncated a 2428-row backfill to
    # just 83 entries. This page has 2 raw rows (== page_size) but only 1
    # parses; pagination must still continue to the next page.
    _unparseable_row = [
        "Jane",
        "Doe",
        "Doe, Jane (Senator)",
        "<a>not a real link</a>",
        "01/01/2026",
    ]
    call_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = urllib.parse.parse_qs(request.read().decode())
        start = int(params["start"][0])
        call_starts.append(start)
        rows = [_ELECTRONIC_ROW, _unparseable_row] if start == 0 else [_PAPER_ROW]
        return httpx.Response(200, json={"data": rows, "result": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler), cookies={"csrftoken": "abc"})
    entries = senate.fetch_ptr_index(client, submitted_start=date(2026, 1, 1), page_size=2)

    assert call_starts == [0, 2]
    assert [e.report_uuid for e in entries] == [
        "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f",
        "929216d5-5dbd-429c-858c-1e9332924627",
    ]


def test_filing_id_for_prefixes_chamber() -> None:
    assert senate.filing_id_for("b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f") == (
        "senate:b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    )


def test_ptr_url_for_builds_the_public_report_view_url() -> None:
    assert senate.ptr_url_for("b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f") == (
        "https://efdsearch.senate.gov/search/view/ptr/b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f/"
    )
