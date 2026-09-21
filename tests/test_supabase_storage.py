import hashlib

from congress_collector.storage.supabase_storage import sha256_hex, upload


def test_sha256_hex_matches_hashlib() -> None:
    content = b"some pdf bytes"
    assert sha256_hex(content) == hashlib.sha256(content).hexdigest()


class _FakeBucket:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def upload(self, path: str, file: bytes, file_options: dict[str, str]) -> None:
        self.calls.append({"path": path, "file": file, "file_options": file_options})


class _FakeStorage:
    def __init__(self, bucket: _FakeBucket) -> None:
        self._bucket = bucket
        self.requested_bucket_ids: list[str] = []

    def from_(self, bucket_id: str) -> _FakeBucket:
        self.requested_bucket_ids.append(bucket_id)
        return self._bucket


class _FakeClient:
    def __init__(self) -> None:
        self.bucket = _FakeBucket()
        self.storage = _FakeStorage(self.bucket)


def test_upload_calls_bucket_with_upsert() -> None:
    client = _FakeClient()

    upload("house/2026/8068.pdf", b"%PDF-1.4 ...", "application/pdf", client=client)

    assert client.storage.requested_bucket_ids == ["congress-raw"]
    assert len(client.bucket.calls) == 1
    call = client.bucket.calls[0]
    assert call["path"] == "house/2026/8068.pdf"
    assert call["file"] == b"%PDF-1.4 ..."
    assert call["file_options"] == {"content-type": "application/pdf", "upsert": "true"}


def test_upload_targets_an_explicit_bucket_when_given() -> None:
    client = _FakeClient()

    upload(
        "congress_20260921.sql.gz",
        b"...",
        "application/gzip",
        bucket="congress-backups",
        client=client,
    )

    assert client.storage.requested_bucket_ids == ["congress-backups"]
