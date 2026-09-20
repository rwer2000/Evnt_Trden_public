"""Fetch and parse the unitedstates/congress-legislators YAML files.

Source: https://github.com/unitedstates/congress-legislators -- current and
historical members of Congress as two flat YAML lists. Structure confirmed
by fetching both files live (unlike disclosures-clerk.house.gov and
efdsearch.senate.gov, raw.githubusercontent.com isn't blocked by this
sandbox's egress proxy):

    - id: {bioguide: A000360, ...}
      name: {first: ..., last: ..., official_full: ..., ...}
      terms:
        - type: rep | sen
          start: 'YYYY-MM-DD'
          end: 'YYYY-MM-DD'
          state: XX
          district: N        # representatives only
          party: ...
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx
import yaml

CURRENT_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/legislators-current.yaml"
)
HISTORICAL_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/legislators-historical.yaml"
)

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"

_CHAMBER_BY_TERM_TYPE = {"rep": "house", "sen": "senate"}


@dataclass(frozen=True)
class TermRecord:
    chamber: str
    state: str | None
    district: str | None
    party: str | None
    start: date
    end: date | None


@dataclass(frozen=True)
class LegislatorRecord:
    bioguide_id: str
    full_name: str
    terms: tuple[TermRecord, ...]


def fetch_all_legislators(*, client: httpx.Client | None = None) -> list[LegislatorRecord]:
    """Fetch and parse both the current and historical legislator lists."""
    owns_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True, timeout=60.0, headers={"User-Agent": USER_AGENT}
    )
    try:
        records: list[LegislatorRecord] = []
        for url in (CURRENT_URL, HISTORICAL_URL):
            response = active_client.get(url)
            response.raise_for_status()
            records.extend(parse_legislators_yaml(response.text))
        return records
    finally:
        if owns_client:
            active_client.close()


def parse_legislators_yaml(text: str) -> list[LegislatorRecord]:
    raw_entries = yaml.safe_load(text) or []
    records = []
    for entry in raw_entries:
        record = _parse_entry(entry)
        if record is not None:
            records.append(record)
    return records


def _parse_entry(entry: dict[str, Any]) -> LegislatorRecord | None:
    bioguide_id = entry.get("id", {}).get("bioguide")
    if not bioguide_id:
        return None

    name = entry.get("name", {})
    full_name = (
        name.get("official_full") or f"{name.get('first', '')} {name.get('last', '')}".strip()
    )

    terms = sorted(
        (t for t in (_parse_term(raw) for raw in entry.get("terms", [])) if t is not None),
        key=lambda t: t.start,
    )
    if not terms:
        return None

    return LegislatorRecord(bioguide_id=bioguide_id, full_name=full_name, terms=tuple(terms))


def _parse_term(raw: dict[str, Any]) -> TermRecord | None:
    chamber = _CHAMBER_BY_TERM_TYPE.get(raw.get("type", ""))
    if chamber is None:
        return None
    start = _parse_date(raw.get("start"))
    if start is None:
        return None

    district = raw.get("district")
    return TermRecord(
        chamber=chamber,
        state=raw.get("state"),
        district=str(district) if district is not None else None,
        party=raw.get("party"),
        start=start,
        end=_parse_date(raw.get("end")),
    )


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d").date()
