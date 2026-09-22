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

A filer-amended report's link text carries a "(Amendment N)" suffix
("Periodic Transaction Report for 12/08/2025 (Amendment 1)") -- confirmed
live (T20's backfill) against real search results, where these turned out
to be ~17% of all rows in one sampled page. `_LINK_RE` originally didn't
allow for that suffix, so it silently dropped every amended filing from
`_parse_rows`; worse, `fetch_ptr_index`'s pagination used the post-regex
row count to decide when it had reached the last page, so a page with any
dropped rows looked artificially short and pagination stopped early --
one bug masking a second, much bigger one (a live backfill run to 2012
only found 83 filings out of a real ~2428, since it silently gave up
after page 1).
"""

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE_URL = "https://efdsearch.senate.gov"
HOME_URL = f"{BASE_URL}/search/home/"
SEARCH_DATA_URL = f"{BASE_URL}/search/report/data/"

PTR_REPORT_TYPE = 11
PAGE_SIZE = 100

# efdsearch.senate.gov occasionally 403s (or 5xx's) a routine GET /search/home/
# -- confirmed live (collect.yml run 35687751405): no code or IP-blocking
# change on our end, the next run 5 minutes later succeeded normally. A
# short retry here is cheap and avoids losing a whole collect.yml cycle's
# worth of Senate + downstream (politician/ticker linking) work to a blip.
MAX_SESSION_ATTEMPTS = 3
RETRY_DELAY_S = 5.0

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"

_LINK_RE = re.compile(
    r'<a href="/search/view/(?P<kind>ptr|paper)/(?P<uuid>[0-9a-f-]{36})/"[^>]*>'
    r"Periodic Transaction Report for \d{2}/\d{2}/\d{4}(?:\s*\(Amendment \d+\))?</a>"
)


@dataclass(frozen=True)
class SenateIndexEntry:
    report_uuid: str
    first_name: str
    last_name: str
    is_electronic: bool
    filed_date: date | None


def new_session(*, client: httpx.Client | None = None) -> httpx.Client:
    """A session with the site's search-prohibition agreement accepted.

    Retries the initial GET up to MAX_SESSION_ATTEMPTS times on an HTTP
    error (see MAX_SESSION_ATTEMPTS's note) before giving up and raising.
    Not retried: the two RuntimeErrors below, since a missing cookie means
    the site responded but not the way we expect -- a format change worth
    surfacing immediately, not a transient blip worth waiting out."""
    session = client or httpx.Client(
        follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT}
    )
    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(MAX_SESSION_ATTEMPTS):
        try:
            response = session.get(HOME_URL)
            response.raise_for_status()
            break
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if attempt < MAX_SESSION_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY_S)
    else:
        assert last_error is not None
        raise last_error

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
    """Fetch all PTR filings submitted on/after `submitted_start`.

    Pagination continues based on the raw row count the site returned,
    not the parsed entry count -- a page can have a full `page_size` raw
    rows but fewer parsed entries if some rows don't match `_LINK_RE`
    (confirmed live: this used to end a 2428-row backfill after just one
    83-entry page, because the other 17 rows on that page were silently
    dropped and made it look like the last page)."""
    entries: list[SenateIndexEntry] = []
    start = 0
    while True:
        raw_rows = _fetch_raw_rows(session, submitted_start, start, page_size)
        entries.extend(_parse_rows(raw_rows))
        if len(raw_rows) < page_size:
            break
        start += page_size
    return entries


def fetch_ptr_page(
    session: httpx.Client, submitted_start: date, start: int, length: int
) -> list[SenateIndexEntry]:
    return _parse_rows(_fetch_raw_rows(session, submitted_start, start, length))


def _fetch_raw_rows(
    session: httpx.Client, submitted_start: date, start: int, length: int
) -> list[list[str]]:
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

    return list(body["data"])


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


def ptr_url_for(report_uuid: str) -> str:
    return f"{BASE_URL}/search/view/ptr/{report_uuid}/"
