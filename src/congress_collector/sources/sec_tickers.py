"""Load the vendored SEC company_tickers.json ticker/CIK/company-name
reference file.

SEC blocks automated fetches of this file from cloud/CI IP ranges outright:
confirmed via a throwaway diagnostic workflow on GitHub Actions (five
attempts -- a plain fetch, a SEC-compliant "Name email" User-Agent, a
different SEC subdomain (data.sec.gov), and a fetch after a 20s delay) that
every one gets a 403, either "Request Rate Threshold Exceeded"
(www.sec.gov) or "Your Request Originates from an Undeclared Automated
Tool" (data.sec.gov). This collector's own dev sandbox gets the same
block. So unlike every other source in this repo, this one isn't fetched
live: it's vendored at ``data/sec_company_tickers.json`` and refreshed
manually every few months (download
https://www.sec.gov/files/company_tickers.json in a regular browser,
replace the file, commit) -- tickers and CIKs change slowly enough that
this is a reasonable trade-off.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "sec_company_tickers.json"


@dataclass(frozen=True)
class SecCompany:
    cik: str  # zero-padded 10-digit string, SEC's own convention
    ticker: str
    title: str


def load_sec_tickers(path: Path = DEFAULT_PATH) -> list[SecCompany]:
    raw = json.loads(path.read_text())
    return parse_sec_tickers(raw)


def parse_sec_tickers(raw: dict[str, Any]) -> list[SecCompany]:
    companies = []
    for entry in raw.values():
        cik = entry.get("cik_str")
        ticker = entry.get("ticker")
        title = entry.get("title")
        if cik is None or not ticker or not title:
            continue
        companies.append(SecCompany(cik=str(cik).zfill(10), ticker=ticker.upper(), title=title))
    return companies
