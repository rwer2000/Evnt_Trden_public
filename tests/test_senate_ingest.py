from datetime import UTC, date, datetime

from congress_collector.ingest.senate import (
    BACKFILL_DAY_PRECISION_S,
    BACKFILL_UNKNOWN_DATE_PRECISION_S,
    backfill_first_seen,
    new_entries,
)
from congress_collector.sources.senate import SenateIndexEntry


def _entry(uuid: str) -> SenateIndexEntry:
    return SenateIndexEntry(
        report_uuid=uuid,
        first_name="Jane",
        last_name="Doe",
        is_electronic=True,
        filed_date=date(2026, 1, 1),
    )


def test_new_entries_excludes_already_seen() -> None:
    entries = [_entry("uuid1"), _entry("uuid2"), _entry("uuid3")]
    existing = {"senate:uuid2"}

    result = new_entries(entries, existing)

    assert [e.report_uuid for e in result] == ["uuid1", "uuid3"]


def test_new_entries_empty_when_all_seen() -> None:
    entries = [_entry("uuid1"), _entry("uuid2")]
    existing = {"senate:uuid1", "senate:uuid2"}

    assert new_entries(entries, existing) == []


def test_new_entries_all_new_when_none_seen() -> None:
    entries = [_entry("uuid1"), _entry("uuid2")]

    assert new_entries(entries, set()) == entries


def test_backfill_first_seen_derives_from_filed_date() -> None:
    entry = _entry("uuid1")

    first_seen_at, precision_s = backfill_first_seen(entry)

    assert first_seen_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert precision_s == BACKFILL_DAY_PRECISION_S


def test_backfill_first_seen_flags_missing_filed_date_as_low_precision() -> None:
    entry = SenateIndexEntry(
        report_uuid="uuid1",
        first_name="Jane",
        last_name="Doe",
        is_electronic=True,
        filed_date=None,
    )

    first_seen_at, precision_s = backfill_first_seen(entry)

    assert first_seen_at.tzinfo is not None
    assert precision_s == BACKFILL_UNKNOWN_DATE_PRECISION_S
