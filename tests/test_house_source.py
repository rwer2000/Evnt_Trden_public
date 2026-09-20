import io
import zipfile
from datetime import date

import httpx

from congress_collector.sources.house import fetch_index, filer_name_for, filing_id_for

SAMPLE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FinancialDisclosure>
  <Member>
    <Prefix />
    <Last>Aaron</Last>
    <First>Richard</First>
    <Suffix />
    <FilingType>W</FilingType>
    <StateDst>MI04</StateDst>
    <Year>2026</Year>
    <FilingDate>4/15/2026</FilingDate>
    <DocID>8068</DocID>
  </Member>
  <Member>
    <Prefix>Hon.</Prefix>
    <Last>Alford</Last>
    <First>Mark</First>
    <Suffix />
    <FilingType>P</FilingType>
    <StateDst>MO04</StateDst>
    <Year>2026</Year>
    <FilingDate>3/31/2026</FilingDate>
    <DocID>20034201</DocID>
  </Member>
</FinancialDisclosure>
"""


def _sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2026FD.xml", SAMPLE_XML)
        zf.writestr("2026FD.txt", b"placeholder")
    return buf.getvalue()


def test_fetch_index_parses_members() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/2026FD.zip")
        return httpx.Response(200, content=_sample_zip_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries = fetch_index(2026, client=client)

    assert len(entries) == 2
    assert entries[0].doc_id == "8068"
    assert entries[0].last == "Aaron"
    assert entries[0].filing_type == "W"
    assert entries[0].filing_date == date(2026, 4, 15)
    assert entries[1].doc_id == "20034201"
    assert entries[1].filing_type == "P"


def test_filing_id_for_prefixes_chamber() -> None:
    assert filing_id_for("8068") == "house:8068"


def test_filer_name_joins_non_empty_parts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sample_zip_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entries = fetch_index(2026, client=client)

    assert filer_name_for(entries[0]) == "Richard Aaron"
    assert filer_name_for(entries[1]) == "Hon. Mark Alford"
