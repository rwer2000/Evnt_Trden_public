"""Look up SEC EDGAR entities (CIK + name) by company name, for traded
tickers that the vendored ``company_tickers.json`` snapshot doesn't list --
in practice delisted, acquired or renamed companies (see
``ingest/sic_backfill.py``).

Uses the entity-name lookup behind EDGAR's own full-text-search box:
``https://efts.sec.gov/LATEST/search-index?keysTyped=<name>``, which returns
an Elasticsearch-style ``{"hits": {"hits": [{"_id": <cik>, "_source":
{"entity": <name>, "tickers": ...}}]}}`` payload covering every EDGAR
filer, including ones that stopped filing years ago. The response shape
is parsed defensively (missing fields are skipped, never guessed) because
it is an undocumented endpoint and could not be exercised from the dev
sandbox (SEC is only reached from GitHub Actions, see assumption A8 in
the strategy repo).

Same User-Agent as ``sources/sec_submissions.py`` (and for the same
reason -- see that module's docstring): SEC's Akamai layer 403s a
descriptive bot User-Agent from GitHub Actions runners. No personal
contact address is ever sent.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from congress_collector.sources.sec_submissions import USER_AGENT

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


@dataclass(frozen=True)
class EdgarEntity:
    cik: str  # zero-padded 10 digits
    name: str
    tickers: tuple[str, ...]


def search_entities(name: str, *, client: httpx.Client) -> list[EdgarEntity]:
    """EDGAR entities whose name matches `name` as a typed-ahead query.
    Raises on any non-2xx response so the caller can stop the run instead
    of hammering an endpoint that's blocking us."""
    response = client.get(SEARCH_URL, params={"keysTyped": name})
    response.raise_for_status()
    return parse_search_index(response.json())


def parse_search_index(raw: Any) -> list[EdgarEntity]:
    if not isinstance(raw, dict):
        return []
    outer = raw.get("hits")
    hits = outer.get("hits") if isinstance(outer, dict) else None
    if not isinstance(hits, list):
        return []

    entities: list[EdgarEntity] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        source = hit.get("_source")
        if not isinstance(source, dict):
            continue
        cik = _parse_cik(hit.get("_id"))
        name = source.get("entity") or source.get("display_names")
        if isinstance(name, list):
            name = name[0] if name else None
        if cik is None or not isinstance(name, str) or not name.strip():
            continue
        entities.append(
            EdgarEntity(cik=cik, name=name.strip(), tickers=_parse_tickers(source.get("tickers")))
        )
    return entities


def _parse_cik(raw: Any) -> str | None:
    text = str(raw).strip() if raw is not None else ""
    if not text.isdigit() or len(text) > 10:
        return None
    return text.zfill(10)


def _parse_tickers(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        parts = raw.replace(",", " ").split()
    elif isinstance(raw, list):
        parts = [p for p in raw if isinstance(p, str)]
    else:
        return ()
    return tuple(p.strip().upper() for p in parts if p.strip())


def new_client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT})
