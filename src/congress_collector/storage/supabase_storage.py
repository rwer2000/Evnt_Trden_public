"""Thin wrapper around the official Supabase client, scoped to the
congress-raw bucket.

Uses the officially maintained `supabase` client rather than hand-rolling
the Storage REST API directly: its upsert/auth semantics are easy to get
subtly wrong, and this is exactly the case the client exists for.
"""

import hashlib
import os
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

BUCKET = "congress-raw"


@lru_cache(maxsize=1)
def get_client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def upload(path: str, content: bytes, content_type: str, *, client: Any | None = None) -> None:
    """Upload `content` to `congress-raw/{path}`, overwriting if present."""
    active_client = client if client is not None else get_client()
    active_client.storage.from_(BUCKET).upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
