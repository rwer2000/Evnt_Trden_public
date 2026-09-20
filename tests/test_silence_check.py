from datetime import UTC, datetime, timedelta

from congress_collector.ops.silence_check import is_silent

THRESHOLD = timedelta(hours=24)
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_no_run_ever_is_silent() -> None:
    assert is_silent(None, NOW, THRESHOLD) is True


def test_recent_run_is_not_silent() -> None:
    last_run = NOW - timedelta(hours=1)
    assert is_silent(last_run, NOW, THRESHOLD) is False


def test_stale_run_is_silent() -> None:
    last_run = NOW - timedelta(hours=25)
    assert is_silent(last_run, NOW, THRESHOLD) is True


def test_run_exactly_at_threshold_is_not_silent() -> None:
    last_run = NOW - THRESHOLD
    assert is_silent(last_run, NOW, THRESHOLD) is False
