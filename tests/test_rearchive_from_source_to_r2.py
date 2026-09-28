import time

import httpx
import pytest

from congress_collector.ops import rearchive_from_source_to_r2 as rearchive
from congress_collector.storage import quota, r2_storage


def test_year_from_object_key() -> None:
    assert rearchive._year_from_object_key("house/2019/10029390.pdf") == 2019


def test_rearchive_house_skips_a_key_already_in_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: "same-hash")

    def fail_get(self: httpx.Client, url: str) -> httpx.Response:
        raise AssertionError("should not fetch an already-migrated key")

    monkeypatch.setattr(httpx.Client, "get", fail_get)

    entries = [("house/2019/1.pdf", "1", "P", 2019)]
    copied, already_present, failed = rearchive.rearchive_house(entries)

    assert (copied, already_present, failed) == (0, 1, [])


def test_rearchive_house_fetches_and_uploads_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: None)
    monkeypatch.setattr(quota, "ensure_budget", lambda bucket, n: None)
    monkeypatch.setattr(quota, "record_bytes", lambda bucket, n: None)
    monkeypatch.setattr(rearchive, "_update_sha256", lambda filing_id, sha256: None)

    def fake_get(self: httpx.Client, url: str) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 ...", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    uploaded = []
    monkeypatch.setattr(
        r2_storage,
        "upload",
        lambda key, content, content_type, *, bucket=r2_storage.BUCKET: uploaded.append(
            (key, content, content_type)
        ),
    )

    entries = [("house/2019/1.pdf", "1", "P", 2019)]
    copied, already_present, failed = rearchive.rearchive_house(entries)

    assert (copied, already_present, failed) == (1, 0, [])
    assert uploaded == [("house/2019/1.pdf", b"%PDF-1.4 ...", "application/pdf")]


def test_rearchive_house_records_a_failed_fetch_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: None)

    def broken_get(self: httpx.Client, url: str) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "get", broken_get)

    entries = [("house/2019/1.pdf", "1", "P", 2019)]
    copied, already_present, failed = rearchive.rearchive_house(entries)

    assert (copied, already_present, failed) == (0, 0, ["house/2019/1.pdf"])


def test_rearchive_senate_skips_a_key_already_in_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: "same-hash")
    monkeypatch.setattr(rearchive, "new_session", lambda: httpx.Client())
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    entries = [("senate/abc.html", "abc")]
    copied, already_present, failed = rearchive.rearchive_senate(entries)

    assert (copied, already_present, failed) == (0, 1, [])
