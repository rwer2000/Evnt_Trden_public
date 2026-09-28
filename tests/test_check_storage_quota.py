import pytest

from congress_collector.ops import check_storage_quota
from congress_collector.storage import quota


def test_check_bucket_reports_the_fraction_of_the_ceiling_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quota, "reconcile", lambda bucket: (8_000_000_000, 100))
    monkeypatch.setattr(quota, "ceiling_bytes", lambda: 10_000_000_000)

    total_bytes, fraction = check_storage_quota.check_bucket("congress-raw")

    assert total_bytes == 8_000_000_000
    assert fraction == pytest.approx(0.8)


def test_main_alerts_once_usage_crosses_the_warn_fraction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1")
    monkeypatch.setattr(quota, "ceiling_bytes", lambda: 10_000_000_000)
    monkeypatch.setattr(quota, "WARN_FRACTION", 0.8)
    monkeypatch.setattr(
        quota,
        "reconcile",
        lambda bucket: (9_000_000_000, 100) if bucket == "congress-raw" else (1_000, 1),
    )

    sent = []
    monkeypatch.setattr(
        check_storage_quota, "send_message", lambda text, category: sent.append((text, category))
    )

    check_storage_quota.main()

    assert len(sent) == 1
    assert "congress-raw" in sent[0][0]
    assert sent[0][1] == "system"


def test_main_sends_no_alert_when_everything_is_under_the_warn_fraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1")
    monkeypatch.setattr(quota, "ceiling_bytes", lambda: 10_000_000_000)
    monkeypatch.setattr(quota, "WARN_FRACTION", 0.8)
    monkeypatch.setattr(quota, "reconcile", lambda bucket: (1_000_000_000, 10))

    sent = []
    monkeypatch.setattr(
        check_storage_quota, "send_message", lambda text, category: sent.append((text, category))
    )

    check_storage_quota.main()

    assert sent == []
