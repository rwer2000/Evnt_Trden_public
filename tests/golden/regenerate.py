"""Regenerate tests/golden/manifest.json from tests/golden/raw/ using the
current parsers.

Run this after an intentional parser change that's meant to alter the
golden set's expected output (e.g. T17's own asset_type fix in
house_ptr.py). Review the resulting diff by hand before committing -- an
unreviewed diff here would defeat the point of the regression gate.
"""

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from congress_collector.parsers.house_ptr import (  # noqa: E402
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.parsers.senate_ptr import parse_ptr_html  # noqa: E402

_GOLDEN_DIR = Path(__file__).parent


def main() -> None:
    manifest: dict[str, dict[str, object]] = {}
    total_tx = 0
    for path in sorted((_GOLDEN_DIR / "raw").iterdir()):
        key = path.name
        content = path.read_bytes()
        if path.suffix == ".pdf":
            pages_words = extract_pages_words(content)
            if not is_electronic(pages_words):
                raise ValueError(f"{key}: not detected as an electronic PDF")
            house_txs = parse_ptr_transactions(pages_words)
            manifest[key] = {
                "chamber": "house",
                "transactions": [dataclasses.asdict(t) for t in house_txs],
            }
            total_tx += len(house_txs)
        else:
            senate_txs = parse_ptr_html(content.decode("utf-8"))
            entries = []
            for t in senate_txs:
                d = dataclasses.asdict(t)
                d["expiry"] = t.expiry.isoformat() if t.expiry else None
                d["tx_date"] = t.tx_date.isoformat() if t.tx_date else None
                entries.append(d)
            manifest[key] = {"chamber": "senate", "transactions": entries}
            total_tx += len(senate_txs)

    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (_GOLDEN_DIR / "manifest.json").write_text(text)
    print(f"Regenerated manifest.json: {len(manifest)} filings, {total_tx} transactions")


if __name__ == "__main__":
    main()
