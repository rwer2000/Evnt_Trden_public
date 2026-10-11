"""Compare two independent Schedule A transcriptions of scanned House annual reports.

Usage::

    python tools/transcription/compare_fd.py --a 'out/*_A.csv' --b 'out/*_B.csv' \
        --merged merged_fd.csv --disagreements disagreements_fd.csv

Both readings follow ``INSTRUCTIONS_FD.md``. Per DocID the script reports
whether the row counts agree, then matches A's rows to B's rows by
normalised asset name (``difflib`` ratio >= 0.85; the best ratio wins, and
on equal ratios the pair closest in reading order). Over the matched pairs
it prints per-field agreement for asset_name, owner, value_band,
income_types and income_amount_band, and lists every disagreement,
including rows only one reading has.

``--merged`` gets one row per matched pair: fields where A and B agree
carry the value, fields where they disagree are left empty and named in
``disagree``; the confidence is the lower of the two. ``--disagreements``
gets one row per field disagreement or unmatched row, for a third look at
the scan.

Standard library only: run it with any Python 3.12.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import glob
import re
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

Row = dict[str, str]

MATCH_THRESHOLD = 0.85
FIELDS = ["asset_name", "owner", "value_band", "income_types", "income_amount_band"]
MERGED_COLUMNS = [
    "doc_id",
    "filer_name",
    "page",
    "row_in_page",
    "asset_name",
    "ticker_on_form",
    "asset_type_code",
    "owner",
    "value_band",
    "income_types",
    "income_amount_band",
    "confidence",
    "disagree",
    "note",
]
DISAGREEMENT_COLUMNS = [
    "doc_id",
    "field",
    "a_page",
    "a_row",
    "a_value",
    "b_page",
    "b_row",
    "b_value",
    "a_asset_name",
    "b_asset_name",
]
RANK = {"high": 2, "medium": 1, "low": 0}


def norm_name(name: str) -> str:
    """Lowercase, keep letters/digits, collapse whitespace."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def norm_value(field: str, value: str) -> str:
    """Normalise a field for comparison (not for output)."""
    v = value.strip().lower().replace("–", "-").replace("—", "-")
    if field == "asset_name":
        return norm_name(v)
    if field == "income_types":
        parts = [norm_name(p) for p in re.split(r"[;,/]", v)]
        return ";".join(sorted(p for p in parts if p))
    return re.sub(r"\s+", "", v)


def name_ratio(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def match_rows(
    ra: Sequence[Row], rb: Sequence[Row], threshold: float = MATCH_THRESHOLD
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Pair A rows with B rows by asset name.

    Returns (pairs of indexes sorted by A index, unmatched A indexes,
    unmatched B indexes). Pairs are assigned greedily: highest name ratio
    first, then the smallest distance in reading order.
    """
    candidates: list[tuple[float, int, int, int]] = []
    for i, x in enumerate(ra):
        for j, y in enumerate(rb):
            r = name_ratio(x.get("asset_name", ""), y.get("asset_name", ""))
            if r >= threshold:
                candidates.append((-r, abs(i - j), i, j))
    candidates.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, _, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    pairs.sort()
    return (
        pairs,
        [i for i in range(len(ra)) if i not in used_a],
        [j for j in range(len(rb)) if j not in used_b],
    )


def _sort_key(r: Row) -> tuple[int, int]:
    def num(s: str) -> int:
        return int(s) if s.strip().isdigit() else 0

    return num(r.get("page", "")), num(r.get("row_in_page", ""))


def load(pattern: str) -> dict[str, list[Row]]:
    by_doc: dict[str, list[Row]] = defaultdict(list)
    for path in sorted(glob.glob(pattern)):
        with open(path, newline="") as fh:
            for raw in csv.DictReader(fh):
                r = {k: (v or "").strip() for k, v in raw.items() if k}
                by_doc[r["doc_id"]].append(r)
    for rows in by_doc.values():
        rows.sort(key=_sort_key)
    return dict(by_doc)


def compare(
    a: dict[str, list[Row]], b: dict[str, list[Row]]
) -> tuple[list[Row], list[Row], dict[str, tuple[int, int]], list[tuple[str, int, int]]]:
    """(merged rows, disagreement rows, field -> (agree, total), row-count mismatches)."""
    merged: list[Row] = []
    disagreements: list[Row] = []
    agreement = {f: (0, 0) for f in FIELDS}
    count_diff: list[tuple[str, int, int]] = []
    for doc in sorted(set(a) | set(b)):
        ra, rb = a.get(doc, []), b.get(doc, [])
        if len(ra) != len(rb):
            count_diff.append((doc, len(ra), len(rb)))
        pairs, only_a, only_b = match_rows(ra, rb)
        for i, j in pairs:
            x, y = ra[i], rb[j]
            out = {k: x.get(k, "") for k in MERGED_COLUMNS}
            bad: list[str] = []
            for f in FIELDS:
                ok = norm_value(f, x.get(f, "")) == norm_value(f, y.get(f, ""))
                agree, total = agreement[f]
                agreement[f] = (agree + ok, total + 1)
                if not ok:
                    bad.append(f)
                    out[f] = ""
                    disagreements.append(_disagreement(doc, f, x, y))
            conf = min(RANK.get(x.get("confidence", ""), 0), RANK.get(y.get("confidence", ""), 0))
            out["confidence"] = {2: "high", 1: "medium", 0: "low"}[conf]
            out["disagree"] = ";".join(bad)
            out["note"] = "; ".join(n for n in (x.get("note"), y.get("note")) if n)
            merged.append(out)
        for i in only_a:
            disagreements.append(_disagreement(doc, "row_only_in_a", ra[i], None))
        for j in only_b:
            disagreements.append(_disagreement(doc, "row_only_in_b", None, rb[j]))
    return merged, disagreements, agreement, count_diff


def _disagreement(doc: str, field: str, x: Row | None, y: Row | None) -> Row:
    value_field = field if field in FIELDS else "asset_name"
    x = x or {}
    y = y or {}
    return {
        "doc_id": doc,
        "field": field,
        "a_page": x.get("page", ""),
        "a_row": x.get("row_in_page", ""),
        "a_value": x.get(value_field, ""),
        "b_page": y.get("page", ""),
        "b_row": y.get("row_in_page", ""),
        "b_value": y.get(value_field, ""),
        "a_asset_name": x.get("asset_name", ""),
        "b_asset_name": y.get("asset_name", ""),
    }


def _write(path: Path, columns: list[str], rows: list[Row]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, help="glob of reading A CSVs")
    p.add_argument("--b", required=True, help="glob of reading B CSVs")
    p.add_argument("--merged", required=True, type=Path)
    p.add_argument("--disagreements", required=True, type=Path)
    args = p.parse_args(argv)
    a, b = load(args.a), load(args.b)
    merged, disagreements, agreement, count_diff = compare(a, b)

    print(f"reports A {len(a)}, B {len(b)}; matched rows {len(merged)}")
    print(f"reports with different row counts: {len(count_diff)}")
    for doc, na, nb in count_diff:
        print(f"  {doc}: A {na}, B {nb}")
    print("per-field agreement on matched rows:")
    for f, (agree, total) in agreement.items():
        pct = f"{100 * agree / total:.1f}%" if total else "n/a"
        print(f"  {f:20s} {agree}/{total} ({pct})")
    print(f"disagreements: {len(disagreements)}")
    for d in disagreements:
        print(
            f"  {d['doc_id']} {d['field']}: A p{d['a_page']}/{d['a_row']}={d['a_value']!r}"
            f"  B p{d['b_page']}/{d['b_row']}={d['b_value']!r}"
        )
    _write(args.merged, MERGED_COLUMNS, merged)
    _write(args.disagreements, DISAGREEMENT_COLUMNS, disagreements)
    print(f"wrote {args.merged} and {args.disagreements}")


if __name__ == "__main__":
    main()
