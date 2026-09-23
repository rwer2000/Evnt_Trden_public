from congress_collector.db.models import Transaction
from congress_collector.ingest.tickers import _resolve
from congress_collector.sources.sec_tickers import SecCompany

_WALMART = SecCompany(cik="0000104169", ticker="WMT", title="WALMART INC")
_APPLE = SecCompany(cik="0000320193", ticker="AAPL", title="Apple Inc.")


def _tx(*, ticker: str | None, description: str) -> Transaction:
    return Transaction(
        filing_id="house:1",
        row_index=0,
        asset_description_raw=description,
        ticker=ticker,
        tx_type="purchase",
    )


def test_resolve_matches_bare_ticker_written_as_the_whole_description() -> None:
    # Some filers write nothing but the ticker itself, with no "(TICKER)"
    # for the PDF parser to extract -- e.g. "WMT" alone as the asset
    # description, so tx.ticker is None going in.
    tx = _tx(ticker=None, description="WMT")
    by_ticker = {"WMT": _WALMART, "AAPL": _APPLE}

    company = _resolve(tx, overrides={}, by_ticker=by_ticker, companies=[_WALMART, _APPLE])

    assert company is _WALMART


def test_resolve_bare_ticker_lookup_is_case_insensitive() -> None:
    tx = _tx(ticker=None, description="wmt")
    by_ticker = {"WMT": _WALMART}

    company = _resolve(tx, overrides={}, by_ticker=by_ticker, companies=[_WALMART])

    assert company is _WALMART


def test_resolve_non_ticker_description_is_not_falsely_matched() -> None:
    # A multi-word description should never collide with the exact-ticker
    # lookup -- it should fall through to (and fail) the fuzzy path.
    tx = _tx(ticker=None, description="US TREASURY BILL")
    by_ticker = {"WMT": _WALMART}

    company = _resolve(tx, overrides={}, by_ticker=by_ticker, companies=[_WALMART])

    assert company is None
