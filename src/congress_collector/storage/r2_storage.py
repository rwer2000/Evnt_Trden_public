"""Thin wrapper around boto3's S3 client, targeting Cloudflare R2.

R2 exposes an S3-compatible API, so boto3 talks to it directly once pointed
at the account's R2 endpoint with an R2 API token instead of AWS
credentials. This is the raw-archive/backup storage backend as of the move
off Supabase Storage (see README's "Database & storage" section) -- the
`congress-raw` bucket outgrew Supabase's free 1 GB Storage quota, which is
shared with the unrelated Sportlogging app in the same Supabase project;
Postgres itself (124 MB at the time of the move) was nowhere near its own,
separate 500 MB quota and stayed put.
"""

import hashlib
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = "congress-raw"


@lru_cache(maxsize=1)
def get_client() -> Any:
    # .strip() guards against a pasted-in trailing newline/space on any of
    # these -- confirmed live: R2_ACCESS_KEY_ID with a trailing "\n" made
    # botocore build an Authorization header with an embedded newline in
    # the credential scope, which http.client's own header validation
    # rejects outright as "Invalid header value".
    account_id = os.environ["R2_ACCOUNT_ID"].strip()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def upload(
    path: str,
    content: bytes,
    content_type: str,
    *,
    bucket: str = BUCKET,
    client: Any | None = None,
) -> None:
    """Upload `content` to `{bucket}/{path}`, overwriting if present. Stores
    the SHA-256 as object metadata so `existing_sha256()` can check whether
    a given key is already migrated without re-downloading it."""
    active_client = client if client is not None else get_client()
    active_client.put_object(
        Bucket=bucket,
        Key=path,
        Body=content,
        ContentType=content_type,
        Metadata={"sha256": sha256_hex(content)},
    )


def download(path: str, *, bucket: str = BUCKET, client: Any | None = None) -> bytes:
    """Download `{bucket}/{path}`."""
    active_client = client if client is not None else get_client()
    result = active_client.get_object(Bucket=bucket, Key=path)
    return result["Body"].read()  # type: ignore[no-any-return]


def existing_sha256(path: str, *, bucket: str = BUCKET, client: Any | None = None) -> str | None:
    """The `sha256` metadata on `{bucket}/{path}` if it already exists in
    R2, else None. A `HEAD` request, not a download -- lets the raw-archive
    migration (`ops/migrate_raw_archive_to_r2.py`) tell "already copied"
    apart from "still needs copying" for 25k+ objects without pulling each
    one down from Supabase just to check."""
    active_client = client if client is not None else get_client()
    try:
        head = active_client.head_object(Bucket=bucket, Key=path)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "404":
            return None
        raise
    metadata: dict[str, str] = head.get("Metadata", {})
    return metadata.get("sha256")


def bucket_totals(bucket: str, *, client: Any | None = None) -> tuple[int, int]:
    """Total size in bytes and object count for every object in `bucket`,
    via a paginated ListObjectsV2 walk. Not for the hot path -- used by
    `storage.quota.reconcile()` to correct the cached running total
    against what's actually in R2."""
    active_client = client if client is not None else get_client()
    paginator = active_client.get_paginator("list_objects_v2")
    total_bytes = 0
    object_count = 0
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            total_bytes += obj["Size"]
            object_count += 1
    return total_bytes, object_count


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
