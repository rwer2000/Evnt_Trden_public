import pytest

from congress_collector.storage import quota


def test_would_exceed_is_false_under_the_ceiling() -> None:
    assert quota.would_exceed(current_bytes=100, additional_bytes=50, ceiling=200) is False


def test_would_exceed_is_false_exactly_at_the_ceiling() -> None:
    assert quota.would_exceed(current_bytes=100, additional_bytes=100, ceiling=200) is False


def test_would_exceed_is_true_over_the_ceiling() -> None:
    assert quota.would_exceed(current_bytes=100, additional_bytes=101, ceiling=200) is True


def test_ceiling_bytes_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R2_STORAGE_CEILING_BYTES", raising=False)

    assert quota.ceiling_bytes() == quota.DEFAULT_CEILING_BYTES


def test_ceiling_bytes_reads_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_STORAGE_CEILING_BYTES", "12345")

    assert quota.ceiling_bytes() == 12345


def test_ensure_budget_raises_when_it_would_exceed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota, "ceiling_bytes", lambda: 1000)
    monkeypatch.setattr(quota, "current_usage_bytes", lambda bucket: 900)

    with pytest.raises(quota.StorageBudgetExceededError):
        quota.ensure_budget("congress-raw", 200)


def test_ensure_budget_passes_when_there_is_room(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota, "ceiling_bytes", lambda: 1000)
    monkeypatch.setattr(quota, "current_usage_bytes", lambda bucket: 900)

    quota.ensure_budget("congress-raw", 50)  # does not raise
