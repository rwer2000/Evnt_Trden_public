"""Fetch and parse the House Clerk's yearly financial disclosure index.

Index format confirmed by fetching a live ZIP from a GitHub Actions runner
(this sandbox's egress proxy blocks the domain, so it couldn't be checked
directly): ``https://disclosures-clerk.house.gov/public_disc/financial-pdfs/
{year}FD.zip`` contains a ``{year}FD.xml`` with a flat list of ``<Member>``
records (DocID, name, FilingType, StateDst, Year, FilingDate).

Filing-type codes (``P`` for periodic transaction report, among others)
are stored as-is rather than filtered here: T8's PTR parser decides what
to do with each type, so nothing observed in the index is dropped.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from xml.etree import ElementTree

import httpx

HOUSE_INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"

USER_AGENT = "congress-collector (personal research use; github.com/rwer2000/Evnt_Trden_public)"


@dataclass(frozen=True)
class HouseIndexEntry:
    doc_id: str
    last: str
    first: str
    prefix: str
    suffix: str
    filing_type: str
    state_dst: str
    year: int
    filing_date: date | None


def fetch_index(year: int, *, client: httpx.Client | None = None) -> list[HouseIndexEntry]:
    """Download and parse the House Clerk's yearly index ZIP for `year`."""
    owns_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT}
    )
    try:
        response = active_client.get(HOUSE_INDEX_URL.format(year=year))
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
            xml_bytes = zf.read(xml_name)
    finally:
        if owns_client:
            active_client.close()

    return _parse_index_xml(xml_bytes)


def _parse_index_xml(xml_bytes: bytes) -> list[HouseIndexEntry]:
    root = ElementTree.fromstring(xml_bytes)
    entries = []
    for member in root.findall("Member"):
        doc_id = (member.findtext("DocID") or "").strip()
        if not doc_id:
            continue
        entries.append(
            HouseIndexEntry(
                doc_id=doc_id,
                last=(member.findtext("Last") or "").strip(),
                first=(member.findtext("First") or "").strip(),
                prefix=(member.findtext("Prefix") or "").strip(),
                suffix=(member.findtext("Suffix") or "").strip(),
                filing_type=(member.findtext("FilingType") or "").strip(),
                state_dst=(member.findtext("StateDst") or "").strip(),
                year=int(member.findtext("Year") or 0),
                filing_date=_parse_date(member.findtext("FilingDate")),
            )
        )
    return entries


def _parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    return datetime.strptime(value.strip(), "%m/%d/%Y").date()


def filing_id_for(doc_id: str) -> str:
    return f"house:{doc_id}"


def filer_name_for(entry: HouseIndexEntry) -> str:
    parts = [entry.prefix, entry.first, entry.last, entry.suffix]
    return " ".join(p for p in parts if p)
