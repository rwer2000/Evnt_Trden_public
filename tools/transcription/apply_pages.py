"""Put a third reader's pages into both readings before comparing.

When readings A and B disagree on the rows of a page (a header line read as a
row, a missed line), a third reader writes the full, correct set of rows for
just those pages (``adj/<group>_C.csv``). This script replaces those pages in
both A and B, so ``compare.py`` then sees agreement there and compares the
rest as usual:

    python tools/transcription/apply_pages.py --a out/g08_A.csv --b out/g08_B.csv \
        --c adj/g08_C.csv --out-dir adj/
"""

import argparse
import csv
from pathlib import Path


def replace_pages(rows: list[dict[str, str]], third: list[dict[str, str]]) -> list[dict[str, str]]:
    """``rows`` with every (doc_id, page) present in ``third`` replaced by the
    third reader's rows, keeping the original order of pages."""
    pages = {(r["doc_id"], r["page"]) for r in third}
    out: list[dict[str, str]] = []
    done: set[tuple[str, str]] = set()
    for r in rows:
        key = (r["doc_id"], r["page"])
        if key not in pages:
            out.append(r)
        elif key not in done:
            out.extend(t for t in third if (t["doc_id"], t["page"]) == key)
            done.add(key)
    # pages only the third reader has (both readings skipped them)
    out.extend(t for t in third if (t["doc_id"], t["page"]) not in done)
    return out


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--c", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    _, third = _read(args.c)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for path in (args.a, args.b):
        fields, rows = _read(path)
        dest = args.out_dir / path.name
        with dest.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(replace_pages(rows, third))
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
