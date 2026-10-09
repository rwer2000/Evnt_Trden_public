"""Compare two independent transcriptions of scanned PTRs and merge them.

Usage::

    python tools/transcription/compare.py --a 'out/*_A.csv' --b 'out/*_B.csv' \
        --out merged.csv [--fixes fixes.json]

Both readings follow ``INSTRUCTIONS.md``. Rows are aligned per DocID in
(page, row) order. The script prints, per field, how often the readings
disagree, and the DocIDs whose row counts differ. Those, and every row with
a disagreement on type, date or band (or very different asset names), need
a third look at the scan; record the outcome in ``fixes.json``::

    {"8219219": {"1/2": {"notification_date": "2022-08-16"}}}

then rerun. ``merged.csv`` is the import format of
``congress_collector.ingest.transcribed_ptrs`` (reading A's values with the
fixes applied, the lower of the two confidences, and a ``review`` note).
DocIDs with differing row counts are left out of ``merged.csv`` until they
are fixed by hand (add the rows to a CSV and concatenate).

Standard library only: run it with any Python 3.12.
"""

import argparse
import csv
import difflib
import glob
import json
from collections import defaultdict
from pathlib import Path

FIELDS = ["owner", "tx_type", "tx_date", "notification_date", "amount_band", "k_flag", "ticker"]
CORE = ["tx_type", "tx_date", "amount_band"]
OUT = [
    "doc_id",
    "page",
    "row",
    "owner",
    "asset_name",
    "ticker",
    "tx_type",
    "tx_date",
    "notification_date",
    "amount_band",
    "k_flag",
    "confidence",
    "review",
    "note",
]
RANK = {"high": 2, "medium": 1, "low": 0}


def load(pattern: str) -> dict[str, list[dict[str, str]]]:
    by_doc: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in sorted(glob.glob(pattern)):
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                r = {k: (v or "").strip() for k, v in r.items() if k}
                by_doc[r["doc_id"]].append(r)
    for rows in by_doc.values():
        rows.sort(key=lambda r: (int(r["page"] or 0), int(r["row"] or 0)))
    return by_doc


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, help="glob of reading A CSVs")
    p.add_argument("--b", required=True, help="glob of reading B CSVs")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--fixes", type=Path)
    args = p.parse_args()
    fixes = json.loads(args.fixes.read_text()) if args.fixes else {}
    a, b = load(args.a), load(args.b)

    disagree = dict.fromkeys(FIELDS, 0)
    count_diff, to_check, merged = [], [], []
    for doc in sorted(set(a) | set(b)):
        ra, rb = a.get(doc, []), b.get(doc, [])
        if len(ra) != len(rb):
            count_diff.append((doc, len(ra), len(rb)))
            continue
        for x, y in zip(ra, rb, strict=True):
            diffs = [f for f in FIELDS if x.get(f, "") != y.get(f, "")]
            for f in diffs:
                disagree[f] += 1
            sim = difflib.SequenceMatcher(
                None, x["asset_name"].lower(), y["asset_name"].lower()
            ).ratio()
            key = f"{x['page']}/{x['row']}"
            fix = fixes.get(doc, {}).get(key)
            core = [f for f in CORE if f in diffs] + (["asset_name"] if sim < 0.6 else [])
            if core and fix is None:
                to_check.append((doc, key, core, x, y))
            out = {k: x.get(k, "") for k in OUT}
            out.update(fix or {})
            conf = min(RANK.get(x["confidence"], 0), RANK.get(y["confidence"], 0))
            out["confidence"] = {2: "high", 1: "medium", 0: "low"}[conf]
            out["review"] = (
                "both readings agree"
                if not diffs and sim >= 0.8
                else "resolved by third look: " + ",".join(diffs or ["asset_name"])
            )
            out["note"] = "; ".join(n for n in (x.get("note"), y.get("note")) if n)
            merged.append(out)

    print(f"filings A {len(a)}, B {len(b)}; rows merged {len(merged)}")
    for f, n in disagree.items():
        print(f"  {f:18s} disagree: {n}")
    print(f"filings with different row counts (left out): {len(count_diff)}")
    for doc, na, nb in count_diff:
        print(f"  {doc}: A {na}, B {nb}")
    print(f"rows needing a third look (no fix yet): {len(to_check)}")
    for doc, key, core, x, y in to_check:
        print(f"  {doc} {key} {core}: A={[x[f] for f in core]} B={[y[f] for f in core]}")
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT)
        w.writeheader()
        w.writerows(merged)
    print(f"wrote {args.out}" + ("" if not to_check else " (unresolved rows still use reading A)"))


if __name__ == "__main__":
    main()
