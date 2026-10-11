"""Find Senate annual Financial Disclosure reports on efdsearch.senate.gov.

Same session and search endpoint as the PTR sync (``sources.senate``):
accept the search agreement, then page through ``POST
/search/report/data/`` -- only with ``report_types=[7]`` ("Annual", the
value of the search form's Annual checkbox) instead of PTR's 11.
Confirmed live from this sandbox on 2026-10-11: 1,602 results for filings
submitted since 2012-01-01 with ``filer_types=[1]`` (senators).

Report type 7 returns more than calendar-year annual reports. Link texts
seen in those 1,602 rows:

- "Annual Report for CY 2025" (858) and "... (Amendment N)" (281);
- "Candidate Report " (44) and "... (Amendment N)" (40) -- the report a
  candidate files, same form;
- "New Filer Report for 07/14/2026" (8) and amendments (1) -- the report a
  newly sworn-in senator files;
- paper filings: "Annual Report" (204), "Annual Report (Amendment)" (164)
  and "Termination" (2), which name no calendar year.

As with PTRs the link path says whether a report is electronic
(``/search/view/annual/<uuid>/``, an HTML page with structured tables) or
paper (``/search/view/paper/<uuid>/``, scanned GIF page images). Paper
reports are all of 2012-2013's filings and 7-29 a year since (2014: 29,
2018: 13, 2025: 10). Unlike every electronic row, about two thirds of the
paper rows (252 of 370) have an UPPER-case UUID in their link, so the
UUID pattern here is case-insensitive.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import httpx

from congress_collector.sources.senate import (
    BASE_URL,
    PAGE_SIZE,
    _fetch_raw_rows,
    _parse_date,
)

ANNUAL_REPORT_TYPE = 7

_LINK_RE = re.compile(
    r'<a href="/search/view/(?P<kind>annual|paper)/(?P<uuid>[0-9a-fA-F-]{36})/"[^>]*>'
    r"(?P<title>[^<]*)</a>"
)
_CY_RE = re.compile(r"\bCY (\d{4})\b")
_AMENDMENT_RE = re.compile(r"\(Amendment(?: (\d+))?\)")


@dataclass(frozen=True)
class SenateAnnualIndexEntry:
    report_uuid: str
    first_name: str
    last_name: str
    office: str
    title: str
    kind: str
    """'annual' (calendar-year report), 'candidate', 'new_filer', or
    'paper' (scanned; the kind of report is only in the images)."""
    calendar_year: int | None
    amendment: int | None
    """None for an original report, N for "(Amendment N)", 0 for a paper
    "(Amendment)" without a number."""
    is_electronic: bool
    filed_date: date | None


def fetch_annual_index(
    session: httpx.Client, *, submitted_start: date, page_size: int = PAGE_SIZE
) -> list[SenateAnnualIndexEntry]:
    """All report-type-7 filings submitted on/after `submitted_start`,
    paginated by raw row count like ``sources.senate.fetch_ptr_index``."""
    entries: list[SenateAnnualIndexEntry] = []
    start = 0
    while True:
        raw_rows = _fetch_raw_rows(
            session, submitted_start, start, page_size, report_type=ANNUAL_REPORT_TYPE
        )
        entries.extend(parse_annual_rows(raw_rows))
        if len(raw_rows) < page_size:
            break
        start += page_size
    return entries


def parse_annual_rows(rows: Sequence[Sequence[str]]) -> list[SenateAnnualIndexEntry]:
    entries = []
    for row in rows:
        first_name, last_name, office, link_html, submitted = row
        match = _LINK_RE.search(link_html)
        if not match:
            continue
        title = " ".join(match.group("title").split())
        is_electronic = match.group("kind") == "annual"
        cy = _CY_RE.search(title)
        amendment = _AMENDMENT_RE.search(title)
        entries.append(
            SenateAnnualIndexEntry(
                report_uuid=match.group("uuid").lower(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                office=office.strip(),
                title=title,
                kind=_kind(title, is_electronic),
                calendar_year=int(cy.group(1)) if cy else None,
                amendment=int(amendment.group(1) or 0) if amendment else None,
                is_electronic=is_electronic,
                filed_date=_parse_date(submitted),
            )
        )
    return entries


def _kind(title: str, is_electronic: bool) -> str:
    if not is_electronic:
        return "paper"
    if title.startswith("Candidate Report"):
        return "candidate"
    if title.startswith("New Filer Report"):
        return "new_filer"
    return "annual"


def annual_view_url(report_uuid: str, *, is_electronic: bool) -> str:
    kind = "annual" if is_electronic else "paper"
    return f"{BASE_URL}/search/view/{kind}/{report_uuid}/"


def fetch_annual_report(session: httpx.Client, report_uuid: str) -> str:
    """One electronic report's HTML page. Needs a session from
    ``sources.senate.new_session``: without the agreement cookie the site
    answers 302 to /search/home/ (confirmed live), which a redirect-following
    client would otherwise return as a 200 agreement page."""
    url = annual_view_url(report_uuid, is_electronic=True)
    response = session.get(url, headers={"Referer": f"{BASE_URL}/search/"})
    response.raise_for_status()
    if str(response.url) != url:
        raise RuntimeError("efdsearch.senate.gov redirected the report view (session expired?)")
    return response.text
