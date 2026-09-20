from pathlib import Path

from congress_collector.ingest.tickers import load_overrides

_HEADER = "match_type,match_value,ticker,cik,reason\n"


def test_loads_ticker_override(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(_HEADER + "ticker,ZZZZ,AAPL,0000320193,typo in filing\n")

    overrides = load_overrides(path)

    assert overrides[("ticker", "ZZZZ")].ticker == "AAPL"
    assert overrides[("ticker", "ZZZZ")].cik == "0000320193"
    assert overrides[("ticker", "ZZZZ")].reason == "typo in filing"


def test_loads_description_override_with_blank_cik(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(_HEADER + "description,Some Weird Fund LP,,,not in SEC data\n")

    overrides = load_overrides(path)

    assert overrides[("description", "Some Weird Fund LP")].ticker is None
    assert overrides[("description", "Some Weird Fund LP")].cik is None


def test_empty_overrides_file_returns_empty_dict(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text(_HEADER)

    assert load_overrides(path) == {}
