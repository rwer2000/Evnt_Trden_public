import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).parent.parent / "tools" / "transcription" / "compare_fd.py"

HEADER = (
    "doc_id,filer_name,page,row_in_page,asset_name,ticker_on_form,asset_type_code,owner,"
    "value_band,income_types,income_amount_band,confidence,note\n"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compare_fd", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_fd"] = module
    spec.loader.exec_module(module)
    return module


compare_fd = _load()


def test_match_rows_is_fuzzy_and_uses_order_as_tie_break() -> None:
    a = [{"asset_name": "Apple Inc."}, {"asset_name": "Cash"}, {"asset_name": "Cash"}]
    b = [{"asset_name": "Cash"}, {"asset_name": "APPLE INC"}, {"asset_name": "Cash"}]
    pairs, only_a, only_b = compare_fd.match_rows(a, b)
    assert pairs == [(0, 1), (1, 0), (2, 2)]
    assert only_a == [] and only_b == []


def test_match_rows_leaves_dissimilar_names_unmatched() -> None:
    pairs, only_a, only_b = compare_fd.match_rows(
        [{"asset_name": "Exxon Mobil"}], [{"asset_name": "Rental property, Ohio"}]
    )
    assert pairs == [] and only_a == [0] and only_b == [0]


def test_main_writes_merged_and_disagreements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "g01_A.csv").write_text(
        HEADER + '1,X,3,1,"Apple, Inc.",,ST,SP,"$15,001 - $50,000",Dividends;Capital Gains,'
        '"$201 - $1,000",high,\n'
        + '1,X,3,2,Rental house,,RP,,"$100,001 - $250,000",Rent,"$2,501 - $5,000",high,\n'
        + "2,Y,,,,,,,,,,high,no schedule A\n"
    )
    (tmp_path / "g01_B.csv").write_text(
        HEADER + '1,X,3,1,"Apple Inc",,ST,SP,"$15,001-$50,000",Capital Gains; Dividends,'
        '"$201 - $1,000",medium,\n'
        + '1,X,3,2,Rental house,,RP,JT,"$50,001 - $100,000",Rent,"$2,501 - $5,000",high,\n'
        + '1,X,4,1,Savings account,,BA,,"$1,001 - $15,000",Interest,None,low,faint\n'
        + "2,Y,,,,,,,,,,high,no schedule A\n"
    )
    merged = tmp_path / "merged.csv"
    dis = tmp_path / "dis.csv"
    compare_fd.main(
        [
            "--a",
            str(tmp_path / "*_A.csv"),
            "--b",
            str(tmp_path / "*_B.csv"),
            "--merged",
            str(merged),
            "--disagreements",
            str(dis),
        ]
    )
    out = capsys.readouterr().out
    assert "1: A 2, B 3" in out
    assert "value_band           2/3" in out

    rows = list(compare_fd.csv.DictReader(merged.open()))
    assert len(rows) == 3
    apple, rental, empty = rows
    assert apple["value_band"] == "$15,001 - $50,000"
    assert apple["confidence"] == "medium" and apple["disagree"] == ""
    assert rental["owner"] == "" and rental["value_band"] == ""
    assert rental["disagree"] == "owner;value_band"
    assert empty["note"] == "no schedule A; no schedule A"

    fields = sorted(r["field"] for r in compare_fd.csv.DictReader(dis.open()))
    assert fields == ["owner", "row_only_in_b", "value_band"]
