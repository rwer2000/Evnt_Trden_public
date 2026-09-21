from datetime import UTC, date, datetime

import pytest

from congress_collector.ingest import senate
from congress_collector.ingest.senate import (
    BACKFILL_DAY_PRECISION_S,
    BACKFILL_UNKNOWN_DATE_PRECISION_S,
    NOTIFY_MAX_LINES,
    backfill_first_seen,
    new_entries,
    notify_new_filings,
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


def test_new_entries_dedupes_repeated_report_uuid_within_a_single_fetch() -> None:
    entries = [_entry("uuid1"), _entry("uuid2"), _entry("uuid1")]

    result = new_entries(entries, set())

    assert [e.report_uuid for e in result] == ["uuid1", "uuid2"]


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


def test_notify_new_filings_sends_one_message_naming_each_filer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [_entry("uuid1"), _entry("uuid2")]
    calls = []
    monkeypatch.setattr(
        senate, "send_message", lambda text, category: calls.append((text, category))
    )

    notify_new_filings(entries)

    assert len(calls) == 1
    text, category = calls[0]
    assert category == "filing"
    assert text.startswith("Senate: 2 new filing(s)")
    assert "Jane Doe" in text
    assert "...and" not in text


def test_notify_new_filings_caps_lines_and_reports_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = [_entry(f"uuid{i}") for i in range(NOTIFY_MAX_LINES + 3)]
    calls = []
    monkeypatch.setattr(
        senate, "send_message", lambda text, category: calls.append((text, category))
    )

    notify_new_filings(entries)

    text, _category = calls[0]
    assert text.startswith(f"Senate: {NOTIFY_MAX_LINES + 3} new filing(s)")
    assert text.count("Jane Doe") == NOTIFY_MAX_LINES
    assert "...and 3 more" in text


def test_notify_new_filings_swallows_send_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # A Telegram outage must never break ingestion -- the one thing this
    # function absolutely cannot fail to do.
    def boom(text: str, category: str) -> None:
        raise RuntimeError("telegram is down")

    monkeypatch.setattr(senate, "send_message", boom)

    notify_new_filings([_entry("uuid1")])
