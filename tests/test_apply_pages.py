import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "apply_pages", Path(__file__).parents[1] / "tools" / "transcription" / "apply_pages.py"
)
assert _spec and _spec.loader
apply_pages = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_pages)


def _r(doc: str, page: str, row: str, name: str) -> dict[str, str]:
    return {"doc_id": doc, "page": page, "row": row, "asset_name": name}


def test_replace_pages_keeps_order_and_swaps_whole_page() -> None:
    a = [
        _r("1", "1", "1", "x"),
        _r("1", "2", "1", "hdr"),
        _r("1", "2", "2", "y"),
        _r("1", "3", "1", "z"),
    ]
    c = [_r("1", "2", "1", "y")]
    got = apply_pages.replace_pages(a, c)
    assert [(r["page"], r["asset_name"]) for r in got] == [("1", "x"), ("2", "y"), ("3", "z")]


def test_page_only_in_third_reading_is_appended() -> None:
    got = apply_pages.replace_pages([_r("1", "1", "1", "x")], [_r("1", "4", "1", "w")])
    assert [r["page"] for r in got] == ["1", "4"]
