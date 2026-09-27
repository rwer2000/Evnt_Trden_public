import pytest

from congress_collector.ops import migrate_raw_archive_to_r2 as migrate
from congress_collector.storage import r2_storage, supabase_storage


def test_content_type_for_known_suffixes() -> None:
    assert migrate._content_type_for("house/2026/1.pdf") == "application/pdf"
    assert migrate._content_type_for("senate/abc.html") == "text/html"
    assert migrate._content_type_for("congress_20260921.sql.gz") == "application/gzip"
    assert migrate._content_type_for("unknown.bin") == "application/octet-stream"


def test_migrate_raw_archive_skips_keys_already_in_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: "same-hash")

    def fail_download(key: str, *, bucket: str) -> bytes:
        raise AssertionError("should not download an already-migrated key")

    monkeypatch.setattr(supabase_storage, "download", fail_download)

    copied, already_present, failed = migrate.migrate_raw_archive([("house/1.pdf", "same-hash")])

    assert (copied, already_present, failed) == (0, 1, [])


def test_migrate_raw_archive_copies_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: None)
    monkeypatch.setattr(supabase_storage, "download", lambda key, *, bucket: b"%PDF-1.4 ...")

    uploaded = []
    monkeypatch.setattr(
        r2_storage,
        "upload",
        lambda key, content, content_type, *, bucket: uploaded.append((key, content, bucket)),
    )

    entries: list[tuple[str, str | None]] = [("house/1.pdf", "expected-hash")]
    copied, already_present, failed = migrate.migrate_raw_archive(entries)

    assert (copied, already_present, failed) == (1, 0, [])
    assert uploaded == [("house/1.pdf", b"%PDF-1.4 ...", migrate.RAW_BUCKET)]


def test_migrate_raw_archive_records_a_failed_key_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: None)

    def broken_download(key: str, *, bucket: str) -> bytes:
        raise RuntimeError("Storage read failed")

    monkeypatch.setattr(supabase_storage, "download", broken_download)

    entries: list[tuple[str, str | None]] = [("house/1.pdf", "expected-hash")]
    copied, already_present, failed = migrate.migrate_raw_archive(entries)

    assert (copied, already_present, failed) == (0, 0, ["house/1.pdf"])


def test_migrate_backups_skips_any_key_already_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: "whatever-hash")

    def fail_download(key: str, *, bucket: str) -> bytes:
        raise AssertionError("should not download an already-migrated key")

    monkeypatch.setattr(supabase_storage, "download", fail_download)

    copied, already_present, failed = migrate.migrate_backups(["congress_20260921.sql.gz"])

    assert (copied, already_present, failed) == (0, 1, [])


def test_migrate_backups_copies_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2_storage, "existing_sha256", lambda key, bucket: None)
    monkeypatch.setattr(supabase_storage, "download", lambda key, *, bucket: b"...")

    uploaded = []
    monkeypatch.setattr(
        r2_storage,
        "upload",
        lambda key, content, content_type, *, bucket: uploaded.append((key, bucket)),
    )

    copied, already_present, failed = migrate.migrate_backups(["congress_20260921.sql.gz"])

    assert (copied, already_present, failed) == (1, 0, [])
    assert uploaded == [("congress_20260921.sql.gz", migrate.BACKUP_BUCKET)]
