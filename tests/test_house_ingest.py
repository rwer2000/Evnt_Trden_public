from datetime import UTC, date, datetime

from congress_collector.ingest.house import (
    BACKFILL_DAY_PRECISION_S,
    BACKFILL_UNKNOWN_DATE_PRECISION_S,
    backfill_first_seen,
    new_entries,
)
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


def test_new_entries_dedupes_repeated_doc_id_within_a_single_fetch() -> None:
    # Confirmed live during T20's backfill: a full year's Clerk index can
    # list the same DocID twice, which would otherwise reach
    # session.add_all() twice and violate the filings primary key.
    entries = [_entry("1"), _entry("2"), _entry("1")]

    result = new_entries(entries, set())

    assert [e.doc_id for e in result] == ["1", "2"]


def test_backfill_first_seen_derives_from_filed_date() -> None:
    # A 2013 filing must not look like it was caught within minutes of
    # filing -- see the module docstring's "Why first seen matters" note.
    entry = _entry("1")

    first_seen_at, precision_s = backfill_first_seen(entry)

    assert first_seen_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert precision_s == BACKFILL_DAY_PRECISION_S


def test_backfill_first_seen_flags_missing_filed_date_as_low_precision() -> None:
    entry = HouseIndexEntry(
        doc_id="1",
        last="Doe",
        first="Jane",
        prefix="",
        suffix="",
        filing_type="P",
        state_dst="CA12",
        year=2026,
        filing_date=None,
    )

    first_seen_at, precision_s = backfill_first_seen(entry)

    assert first_seen_at.tzinfo is not None
    assert precision_s == BACKFILL_UNKNOWN_DATE_PRECISION_S
