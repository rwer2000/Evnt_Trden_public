from congress_collector.parsers.house_ptr import ParsedTransaction
from congress_collector.parsers.scan_verification import verify_extraction


def _tx(**overrides: object) -> ParsedTransaction:
    defaults: dict[str, object] = {
        "row_index": 0,
        "owner": "self",
        "asset_description_raw": "Apple Inc. (AAPL)",
        "ticker": "AAPL",
        "asset_type": "ST",
        "option_type": None,
        "strike": None,
        "expiry": None,
        "tx_type": "purchase",
        "tx_date": "2024-01-01",
        "notification_date": "2024-01-15",
        "amount_min": 1001.0,
        "amount_max": 15000.0,
        "source_transaction_id": None,
    }
    defaults.update(overrides)
    return ParsedTransaction(**defaults)  # type: ignore[arg-type]


def test_accepts_a_clean_small_extraction() -> None:
    result = verify_extraction([_tx(row_index=0), _tx(row_index=1, ticker="MSFT")])

    assert result.ok
    assert not result.needs_review


def test_rejects_any_blank_asset_description() -> None:
    result = verify_extraction([_tx(asset_description_raw=""), _tx(asset_description_raw="  ")])

    assert not result.ok
    assert any("blank asset_description_raw" in r for r in result.reasons)


def test_flags_large_filings_for_review_without_rejecting() -> None:
    transactions = [_tx(row_index=i) for i in range(25)]

    result = verify_extraction(transactions)

    assert result.ok
    assert result.needs_review
    assert any("exceeds" in r for r in result.reasons)


def test_flags_repeated_identical_rows_for_review() -> None:
    transactions = [_tx(row_index=i) for i in range(3)]  # identical fields, 3 times

    result = verify_extraction(transactions)

    assert result.ok
    assert result.needs_review
    assert any("hallucinated-repetition" in r for r in result.reasons)


def test_flags_empty_extraction_for_review() -> None:
    result = verify_extraction([])

    assert result.ok
    assert result.needs_review
    assert any("zero transactions" in r for r in result.reasons)


def test_ignores_reported_total_rows_when_not_given() -> None:
    result = verify_extraction([_tx()])

    assert result.ok
    assert not result.needs_review


def test_flags_mismatch_between_reported_and_extracted_row_count() -> None:
    result = verify_extraction([_tx(), _tx(row_index=1)], reported_total_rows=5)

    assert result.ok
    assert result.needs_review
    assert any("self-reported 5" in r for r in result.reasons)


def test_accepts_when_reported_total_rows_matches() -> None:
    result = verify_extraction([_tx(), _tx(row_index=1)], reported_total_rows=2)

    assert result.ok
    assert not result.needs_review


def test_flags_low_density_multi_page_filing_for_review() -> None:
    # 6 pages, 3 distinct transactions -- well under the 4/page floor,
    # mirrors the real house:8218645 case (6 pages, 20 of an estimated
    # 100+). Distinct descriptions so this doesn't also trip the
    # duplicate-row check, keeping the assertion specific to density.
    transactions = [_tx(row_index=i, asset_description_raw=f"Company {i} Inc.") for i in range(3)]

    result = verify_extraction(transactions, page_count=6)

    assert result.ok
    assert result.needs_review
    assert any("below the" in r and "/page floor" in r for r in result.reasons)


def test_does_not_flag_density_on_short_filings() -> None:
    # 2 pages, 1 transaction is entirely normal -- the density check only
    # applies once a filing is long enough (PAGES_FOR_DENSITY_CHECK) that a
    # low rate becomes suspicious rather than just being a short filing.
    result = verify_extraction([_tx()], page_count=2)

    assert result.ok
    assert not result.needs_review


def test_does_not_flag_density_when_rate_is_healthy() -> None:
    # 4 pages, 22 transactions (5.5/page) mirrors the real house:20019240
    # case, which was a fully correct extraction.
    transactions = [_tx(row_index=i) for i in range(22)]

    result = verify_extraction(transactions, page_count=4)

    assert not any("/page floor" in r for r in result.reasons)
