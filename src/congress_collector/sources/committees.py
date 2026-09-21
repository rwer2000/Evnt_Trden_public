"""Fetch and parse the unitedstates/congress-legislators committee files.

Source: https://github.com/unitedstates/congress-legislators -- the same
repo T13's legislators.py already pulls politicians from. Two files:

    committees-current.yaml:
        - type: house | senate | joint
          name: Committee on Agriculture
          thomas_id: HSAG
          subcommittees:
            - name: Subcommittee on ...
              thomas_id: HSAG14
          ...

    committee-membership-current.yaml:
        HSAG:
          - name: David Rouzer
            party: majority
            rank: 1
            title: Chairman        # optional -- only chairs/ranking members
            bioguide: R000603
        HSAG14:                    # subcommittee -- see below
          - ...

Subcommittee memberships are dropped: this collector only needs "which
committees is this person on" at a glance for the Telegram notification
(T22) and T25's planned sector-overlap flag, and subcommittee membership
multiplies the row count several-fold without adding a meaningfully
different jurisdiction signal.
"""

from dataclasses import dataclass
from typing import Any

import httpx
import yaml

COMMITTEES_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/committees-current.yaml"
)
MEMBERSHIP_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators"
    "/main/committee-membership-current.yaml"
)

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"

_CHAMBERS = {"house", "senate", "joint"}


@dataclass(frozen=True)
class CommitteeRecord:
    thomas_id: str
    chamber: str
    name: str


@dataclass(frozen=True)
class MembershipRecord:
    thomas_id: str
    bioguide_id: str
    party: str | None
    rank: int | None
    title: str | None


def fetch_committees_and_memberships(
    *, client: httpx.Client | None = None
) -> tuple[list[CommitteeRecord], list[MembershipRecord]]:
    """Fetch+parse both files. Membership rows are filtered to the
    top-level committees returned in the first element, so the caller
    never has to filter subcommittee rows itself."""
    owns_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True, timeout=60.0, headers={"User-Agent": USER_AGENT}
    )
    try:
        committees_response = active_client.get(COMMITTEES_URL)
        committees_response.raise_for_status()
        committees = parse_committees_yaml(committees_response.text)

        membership_response = active_client.get(MEMBERSHIP_URL)
        membership_response.raise_for_status()
        known_thomas_ids = {c.thomas_id for c in committees}
        memberships = parse_membership_yaml(
            membership_response.text, known_thomas_ids=known_thomas_ids
        )

        return committees, memberships
    finally:
        if owns_client:
            active_client.close()


_YAML_LOADER: type[yaml.Loader] | type[yaml.CSafeLoader] | type[yaml.SafeLoader]
try:
    _YAML_LOADER = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - depends on libyaml being available
    _YAML_LOADER = yaml.SafeLoader


def parse_committees_yaml(text: str) -> list[CommitteeRecord]:
    raw_entries = yaml.load(text, Loader=_YAML_LOADER) or []
    records = []
    for entry in raw_entries:
        record = _parse_committee(entry)
        if record is not None:
            records.append(record)
    return records


def parse_membership_yaml(text: str, *, known_thomas_ids: set[str]) -> list[MembershipRecord]:
    raw = yaml.load(text, Loader=_YAML_LOADER) or {}
    records = []
    for thomas_id, members in raw.items():
        if thomas_id not in known_thomas_ids:
            continue
        for m in members or []:
            record = _parse_membership(thomas_id, m)
            if record is not None:
                records.append(record)
    return records


def _parse_committee(entry: dict[str, Any]) -> CommitteeRecord | None:
    thomas_id = entry.get("thomas_id")
    chamber = entry.get("type")
    name = entry.get("name")
    if not thomas_id or chamber not in _CHAMBERS or not name:
        return None
    return CommitteeRecord(thomas_id=thomas_id, chamber=chamber, name=name)


def _parse_membership(thomas_id: str, entry: dict[str, Any]) -> MembershipRecord | None:
    bioguide_id = entry.get("bioguide")
    if not bioguide_id:
        return None
    return MembershipRecord(
        thomas_id=thomas_id,
        bioguide_id=bioguide_id,
        party=entry.get("party"),
        rank=entry.get("rank"),
        title=entry.get("title"),
    )
