from congress_collector.db.models import Politician, Transaction
from congress_collector.ingest.senate_ptrs import describe_filer, describe_transaction


def _politician(**overrides: str | None) -> Politician:
    defaults: dict[str, str | None] = {
        "bioguide_id": "W000001",
        "full_name": "Ron Wyden",
        "chamber": "senate",
        "party": "D",
        "state": "OR",
        "district": None,
    }
    defaults.update(overrides)
    return Politician(**defaults)


def _transaction(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "filing_id": "senate:uuid1",
        "row_index": 0,
        "owner": "spouse",
        "asset_description_raw": "Beyond Meat, Inc.",
        "ticker": "BYND",
        "tx_type": "sale_full",
        "amount_min": 50001,
        "amount_max": 100000,
    }
    defaults.update(overrides)
    return Transaction(**defaults)


def test_describe_filer_uses_politician_party_and_state_when_linked() -> None:
    assert describe_filer("Wyden, Ron", _politician()) == "Ron Wyden (D-OR)"


def test_describe_filer_falls_back_to_raw_filer_name_when_unlinked() -> None:
    assert describe_filer("Wyden, Ron", None) == "Wyden, Ron"


def test_describe_filer_appends_committees_in_brackets() -> None:
    result = describe_filer("Wyden, Ron", _politician(), ["Finance (Chairman)"])

    assert result == "Ron Wyden (D-OR) [Finance (Chairman)]"


def test_describe_filer_caps_committees_and_reports_remainder() -> None:
    committees = ["A", "B", "C", "D"]

    result = describe_filer("Wyden, Ron", _politician(), committees)

    assert result == "Ron Wyden (D-OR) [A, B, C, +1 more]"


def test_describe_transaction_formats_sell_with_ticker_amount_and_owner() -> None:
    t = _transaction()

    assert describe_transaction(t) == "SELL BYND $50,001-$100,000 [spouse]"


def test_describe_transaction_falls_back_to_asset_description_without_ticker() -> None:
    t = _transaction(ticker=None, asset_description_raw="US Treasury Note 2.5% 2028")

    assert "US Treasury Note 2.5% 2028" in describe_transaction(t)


def test_describe_transaction_omits_amount_when_missing() -> None:
    t = _transaction(amount_min=None, amount_max=None)

    assert describe_transaction(t) == "SELL BYND [spouse]"
