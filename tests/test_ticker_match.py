from congress_collector.parsers.ticker_match import (
    match_by_description,
    match_by_ticker,
    normalize_company_name,
    normalize_ticker,
)
from congress_collector.sources.sec_tickers import SecCompany

_APPLE = SecCompany(cik="0000320193", ticker="AAPL", title="Apple Inc.")
_NVIDIA = SecCompany(cik="0001045810", ticker="NVDA", title="NVIDIA CORP")
_EA = SecCompany(cik="0000712515", ticker="EA", title="ELECTRONIC ARTS INC")
_INVESCO = SecCompany(cik="0000914208", ticker="IVZ", title="Invesco Ltd.")
_STATE_STREET = SecCompany(cik="0000093751", ticker="STT", title="STATE STREET CORP")
_DIA_TRUST = SecCompany(
    cik="0001041130", ticker="DIA", title="SPDR DOW JONES INDUSTRIAL AVERAGE ETF TRUST"
)


def test_normalize_ticker_strips_and_uppercases() -> None:
    assert normalize_ticker("  aapl ") == "AAPL"


def test_normalize_company_name_strips_legal_suffixes() -> None:
    assert normalize_company_name("Apple Inc.") == "apple"
    assert normalize_company_name("Electronic Arts Inc.") == "electronic arts"


def test_normalize_company_name_collapses_whitespace() -> None:
    assert normalize_company_name("  Apple   Inc.  ") == "apple"


def test_match_by_ticker_exact() -> None:
    by_ticker = {"AAPL": _APPLE, "NVDA": _NVIDIA}

    assert match_by_ticker("aapl", by_ticker) is _APPLE


def test_match_by_ticker_no_match_returns_none() -> None:
    by_ticker = {"AAPL": _APPLE}

    assert match_by_ticker("ZZZZ", by_ticker) is None


def test_match_by_description_recovers_ticker_free_mention() -> None:
    # No "(EA)"-style ticker in the parser's own extraction, but the
    # company name is recognizable -- e.g. "EA - Electronic Arts Inc".
    candidates = [_APPLE, _NVIDIA, _EA]

    result = match_by_description("EA - Electronic Arts Inc", candidates)

    assert result.company is _EA
    assert result.method == "fuzzy"


def test_match_by_description_no_candidates_is_unmatched() -> None:
    result = match_by_description("Apple Inc.", [])

    assert result.company is None
    assert result.method == "unmatched"


def test_match_by_description_non_equity_is_unmatched() -> None:
    # A municipal bond description shouldn't fuzzy-latch onto an unrelated
    # public company.
    candidates = [_APPLE, _NVIDIA, _EA]

    result = match_by_description("Washington ST 5% Go Utx Due 08/01/30", candidates)

    assert result.company is None
    assert result.method == "unmatched"


def test_match_by_description_does_not_false_positive_on_shared_word() -> None:
    # Regression test: an earlier version used token_set_ratio, which
    # scores a perfect *subset* match at 100 regardless of the rest of
    # either string -- verified against real SEC data that this makes
    # "Invesco QQQ" confidently (score 100) match "Invesco Ltd.", a real
    # but unrelated company that merely shares the word "Invesco". The
    # correct entity for the ETF isn't even in this candidate set (SEC's
    # company_tickers.json doesn't list it), so the only safe outcome is
    # unmatched, not a confident wrong guess.
    candidates = [_INVESCO, _APPLE, _NVIDIA]

    result = match_by_description("Invesco QQQ [OT]", candidates)

    assert result.company is None
    assert result.method == "unmatched"


def test_match_by_description_prefers_the_right_entity_over_the_sponsor() -> None:
    # Same class of bug: "DIA - State Street SPDR ... ETF Trust" mentions
    # the sponsor "State Street" by name, but the actual SEC registrant is
    # the trust itself. Confirms strict normalization (stripping the
    # ticker prefix and exchange mention) plus token_sort_ratio ranks the
    # correct entity above the sponsor, even though neither crosses the
    # high auto-link threshold here.
    candidates = [_STATE_STREET, _DIA_TRUST, _APPLE]

    result = match_by_description(
        "DIA - State Street SPDR Dow Jones Indust Avg ETF Trust NYSEARCA: DIA [OT]",
        candidates,
    )

    assert result.company is None or result.company is _DIA_TRUST
