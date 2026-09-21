"""T17: golden set of manually-verified real filings, used as a CI
regression gate for the House and Senate PTR parsers.

Parsing is deterministic, so "score must not decrease" (per the plan) is
enforced via exact-match snapshot tests against `tests/golden/manifest.json`
rather than a fuzzy scoring threshold: any parser change that alters the
parsed output for one of these real filings fails here. A deliberate
improvement (like T17's own asset_type fix, see house_ptr.py) regenerates
the manifest in the same PR as the parser change.

The 52 filings under `tests/golden/raw/` were pulled from production via a
GitHub Actions run (this sandbox can't reach Supabase Storage directly) and
selected to span: every House asset_type seen in real data (including ones
with no ticker, like government securities and private holdings), both
option description styles, an amendment pair, partial sales, exchanges, all
owner codes, and Senate stock/option/multi-transaction filings.

To regenerate the manifest after an intentional parser change:
    uv run python tests/golden/regenerate.py
"""

import dataclasses
import json
from pathlib import Path

import pytest

from congress_collector.parsers.house_ptr import (
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.parsers.senate_ptr import parse_ptr_html

_GOLDEN_DIR = Path(__file__).parent / "golden"
_MANIFEST = json.loads((_GOLDEN_DIR / "manifest.json").read_text())


def _parse(key: str) -> list[dict[str, object]]:
    content = (_GOLDEN_DIR / "raw" / key).read_bytes()
    if key.endswith(".pdf"):
        pages_words = extract_pages_words(content)
        assert is_electronic(pages_words), f"{key}: no longer detected as an electronic PDF"
        return [dataclasses.asdict(t) for t in parse_ptr_transactions(pages_words)]

    results: list[dict[str, object]] = []
    for t in parse_ptr_html(content.decode("utf-8")):
        d = dataclasses.asdict(t)
        d["expiry"] = t.expiry.isoformat() if t.expiry else None
        d["tx_date"] = t.tx_date.isoformat() if t.tx_date else None
        results.append(d)
    return results


@pytest.mark.parametrize("key", sorted(_MANIFEST))
def test_golden_filing_parses_exactly_as_expected(key: str) -> None:
    expected = _MANIFEST[key]["transactions"]
    assert _parse(key) == expected


def test_manifest_covers_both_chambers() -> None:
    chambers = {v["chamber"] for v in _MANIFEST.values()}
    assert chambers == {"house", "senate"}


def test_manifest_has_no_unparsed_filings() -> None:
    empty = [key for key, v in _MANIFEST.items() if not v["transactions"]]
    assert empty == []
