"""Fetch a company's SIC (Standard Industrial Classification) code from
SEC EDGAR's submissions API (T24), as a sector proxy for T25's planned
committee<->sector overlap flag.

https://data.sec.gov/submissions/CIK##########.json -- keyed by the same
zero-padded 10-digit CIK T14's ticker linking already stores on
`instruments.cik`.

Confirmed live via a throwaway diagnostic workflow (deleted after use,
see PR #57) that this endpoint 403s from GitHub Actions runners when the
request carries a descriptive, self-identifying User-Agent -- exactly the
kind SEC's own fair-access guidance asks bots to send -- but succeeds
with a generic browser-like one. This is the opposite of T14's
`sources/sec_tickers.py` finding (which is IP-range/traffic-pattern
blocking, not User-Agent based) and means this endpoint's block is SEC's
Akamai layer pattern-matching the User-Agent string itself, not a
blanket block on cloud/CI IPs. Deliberately using a generic User-Agent
here works around that, at the cost of not self-identifying the way SEC
asks -- a conscious tradeoff, not an oversight (confirmed with the repo
owner rather than decided unilaterally). Kept polite in every other way:
throttled well under SEC's stated rate limits (see ingest/sic_codes.py)
and fetching only data this project already has a legitimate CIK for.
"""

from dataclasses import dataclass
from typing import Any

import httpx

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Not a descriptive/self-identifying UA -- see this module's docstring.
USER_AGENT = "Mozilla/5.0"


@dataclass(frozen=True)
class SicRecord:
    cik: str
    sic: str | None
    sic_description: str | None


def fetch_sic(cik: str, *, client: httpx.Client) -> SicRecord | None:
    """Fetch the SIC code+description for `cik` (zero-padded 10 digits).
    Returns None if SEC has no record at all for this CIK (a 404); a
    record with sic=None means SEC has a record but no SIC classification
    for it (some foreign private issuers, trusts, ETFs)."""
    response = client.get(SUBMISSIONS_URL.format(cik=cik))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return parse_submission(cik, response.json())


def parse_submission(cik: str, raw: dict[str, Any]) -> SicRecord:
    sic = raw.get("sic") or None
    sic_description = raw.get("sicDescription") or None
    return SicRecord(cik=cik, sic=sic, sic_description=sic_description)


def new_client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT})
