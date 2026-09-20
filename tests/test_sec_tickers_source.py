from congress_collector.sources.sec_tickers import parse_sec_tickers

SAMPLE = {
    "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": None, "ticker": "XXXX", "title": "Missing CIK"},
    "3": {"cik_str": 1, "ticker": "", "title": "Empty Ticker"},
    "4": {"cik_str": 1, "ticker": "YYYY", "title": ""},
}


def test_parses_entries_into_companies() -> None:
    companies = parse_sec_tickers(SAMPLE)

    assert len(companies) == 2


def test_ticker_is_uppercased() -> None:
    companies = parse_sec_tickers(SAMPLE)
    apple = next(c for c in companies if c.title == "Apple Inc.")

    assert apple.ticker == "AAPL"


def test_cik_is_zero_padded_to_ten_digits() -> None:
    companies = parse_sec_tickers(SAMPLE)
    apple = next(c for c in companies if c.title == "Apple Inc.")

    assert apple.cik == "0000320193"


def test_entries_missing_cik_ticker_or_title_are_skipped() -> None:
    companies = parse_sec_tickers(SAMPLE)

    assert {c.title for c in companies} == {"Apple Inc.", "NVIDIA CORP"}


def test_empty_document_returns_no_companies() -> None:
    assert parse_sec_tickers({}) == []
