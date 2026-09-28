import hashlib

from botocore.exceptions import ClientError

from congress_collector.storage.r2_storage import download, existing_sha256, sha256_hex, upload


def test_sha256_hex_matches_hashlib() -> None:
    content = b"some pdf bytes"
    assert sha256_hex(content) == hashlib.sha256(content).hexdigest()


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, Metadata: dict[str, str]
    ) -> None:
        self.put_calls.append(
            {"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType}
        )
        self.objects[(Bucket, Key)] = (Body, Metadata)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        content, _metadata = self.objects[(Bucket, Key)]
        return {"Body": _FakeBody(content)}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        stored = self.objects.get((Bucket, Key))
        if stored is None:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        _content, metadata = stored
        return {"Metadata": metadata}


class _FakeBody:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content


def test_upload_then_download_round_trips() -> None:
    client = _FakeS3Client()

    upload("house/2026/8068.pdf", b"%PDF-1.4 ...", "application/pdf", client=client)

    assert client.put_calls == [
        {
            "Bucket": "congress-raw",
            "Key": "house/2026/8068.pdf",
            "Body": b"%PDF-1.4 ...",
            "ContentType": "application/pdf",
        }
    ]
    assert download("house/2026/8068.pdf", client=client) == b"%PDF-1.4 ..."


def test_upload_targets_an_explicit_bucket_when_given() -> None:
    client = _FakeS3Client()

    upload(
        "congress_20260921.sql.gz",
        b"...",
        "application/gzip",
        bucket="congress-backups",
        client=client,
    )

    assert client.put_calls[0]["Bucket"] == "congress-backups"


def test_existing_sha256_matches_what_was_uploaded() -> None:
    client = _FakeS3Client()
    content = b"%PDF-1.4 ..."

    upload("house/2026/8068.pdf", content, "application/pdf", client=client)

    assert existing_sha256("house/2026/8068.pdf", client=client) == sha256_hex(content)


def test_existing_sha256_is_none_for_a_missing_key() -> None:
    client = _FakeS3Client()

    assert existing_sha256("house/2026/does-not-exist.pdf", client=client) is None
