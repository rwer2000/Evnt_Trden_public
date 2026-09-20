"""Fetch new Senate PTR filings via efdsearch.senate.gov's search endpoint.

Session flow confirmed live from a GitHub Actions runner (this sandbox's
egress proxy blocks the domain): GET /search/home/ for a CSRF token, POST
the same URL with prohibition_agreement=1 to accept the site's terms
(sets a session cookie), then POST /search/report/data/ (a DataTables
server-side endpoint) for search results as JSON. The CSRF cookie's raw
value works directly as csrfmiddlewaretoken -- the page also renders a
separate masked token in a hidden input, but the unmasked cookie value is
accepted too (a standard Django CSRF detail), which avoids needing to
parse the HTML form at all.

Report type 11 is "Periodic Transaction Report" -- confirmed by
searching for it and getting back only PTR results. The result link path
itself says whether a filing is electronic (`/search/view/ptr/<uuid>/`,
rendered as an HTML page) or paper (`/search/view/paper/<uuid>/`), so no
separate content-based classification step is needed the way House's
PDF-based filings require.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE_URL = "https://efdsearch.senate.gov"
HOME_URL = f"{BASE_URL}/search/home/"
SEARCH_DATA_URL = f"{BASE_URL}/search/report/data/"

PTR_REPORT_TYPE = 11
PAGE_SIZE = 100

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"

_LINK_RE = re.compile(
    r'<a href="/search/view/(?P<kind>ptr|paper)/(?P<uuid>[0-9a-f-]{36})/"[^>]*>'
    r"Periodic Transaction Report for \d{2}/\d{2}/\d{4}</a>"
)


@dataclass(frozen=True)
class SenateIndexEntry:
    report_uuid: str
    first_name: str
    last_name: str
    is_electronic: bool
    filed_date: date | None


def new_session(*, client: httpx.Client | None = None) -> httpx.Client:
    """A session with the site's search-prohibition agreement accepted."""
    session = client or httpx.Client(
        follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT}
    )
    response = session.get(HOME_URL)
    response.raise_for_status()
    csrf_token = session.cookies.get("csrftoken")
    if not csrf_token:
        raise RuntimeError("efdsearch.senate.gov did not set a csrftoken cookie")

    accept = session.post(
        HOME_URL,
        data={"csrfmiddlewaretoken": csrf_token, "prohibition_agreement": "1"},
        headers={"Referer": HOME_URL},
    )
    accept.raise_for_status()
    if "sessionid" not in session.cookies:
        raise RuntimeError("efdsearch.senate.gov did not accept the search agreement")
    return session


def fetch_ptr_index(
    session: httpx.Client, *, submitted_start: date, page_size: int = PAGE_SIZE
) -> list[SenateIndexEntry]:
    """Fetch all PTR filings submitted on/after `submitted_start`."""
    entries: list[SenateIndexEntry] = []
    start = 0
    while True:
        page = fetch_ptr_page(session, submitted_start, start, page_size)
        if not page:
            break
        entries.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return entries


def fetch_ptr_page(
    session: httpx.Client, submitted_start: date, start: int, length: int
) -> list[SenateIndexEntry]:
    csrf_token = session.cookies.get("csrftoken")
    payload = {
        "csrfmiddlewaretoken": csrf_token,
        "report_types": f"[{PTR_REPORT_TYPE}]",
        "filer_types": "[]",
        "submitted_start_date": submitted_start.strftime("%m/%d/%Y 00:00:00"),
        "submitted_end_date": "",
        "candidate_state": "",
        "senator_state": "",
        "office_id": "",
        "first_name": "",
        "last_name": "",
        "start": str(start),
        "length": str(length),
    }
    response = session.post(
        SEARCH_DATA_URL,
        data=payload,
        headers={"Referer": f"{BASE_URL}/search/", "X-Requested-With": "XMLHttpRequest"},
    )
    response.raise_for_status()
    body = response.json()
    if body.get("result") != "ok":
        raise RuntimeError(f"efdsearch search returned an error: {body}")

    return _parse_rows(body["data"])


def _parse_rows(rows: Sequence[Sequence[str]]) -> list[SenateIndexEntry]:
    entries = []
    for row in rows:
        first_name, last_name, _office, link_html, submitted = row
        match = _LINK_RE.search(link_html)
        if not match:
            continue
        entries.append(
            SenateIndexEntry(
                report_uuid=match.group("uuid"),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                is_electronic=match.group("kind") == "ptr",
                filed_date=_parse_date(submitted),
            )
        )
    return entries


def _parse_date(raw: str) -> date | None:
    if not raw or not raw.strip():
        return None
    return datetime.strptime(raw.strip(), "%m/%d/%Y").date()


def filing_id_for(report_uuid: str) -> str:
    return f"senate:{report_uuid}"


def filer_name_for(entry: SenateIndexEntry) -> str:
    return f"{entry.first_name} {entry.last_name}".strip()
