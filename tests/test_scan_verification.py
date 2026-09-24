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
