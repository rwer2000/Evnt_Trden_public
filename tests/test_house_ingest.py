from datetime import date

from congress_collector.ingest.house import new_entries
from congress_collector.sources.house import HouseIndexEntry


def _entry(doc_id: str) -> HouseIndexEntry:
    return HouseIndexEntry(
        doc_id=doc_id,
        last="Doe",
        first="Jane",
        prefix="",
        suffix="",
        filing_type="P",
        state_dst="CA12",
        year=2026,
        filing_date=date(2026, 1, 1),
    )


def test_new_entries_excludes_already_seen() -> None:
    entries = [_entry("1"), _entry("2"), _entry("3")]
    existing = {"house:2"}

    result = new_entries(entries, existing)

    assert [e.doc_id for e in result] == ["1", "3"]


def test_new_entries_empty_when_all_seen() -> None:
    entries = [_entry("1"), _entry("2")]
    existing = {"house:1", "house:2"}

    assert new_entries(entries, existing) == []


def test_new_entries_all_new_when_none_seen() -> None:
    entries = [_entry("1"), _entry("2")]

    assert new_entries(entries, set()) == entries
