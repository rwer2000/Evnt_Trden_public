from congress_collector.db.models import Politician, Transaction
from congress_collector.ingest.house_ptrs import describe_filer, describe_transaction


def _politician(**overrides: str | None) -> Politician:
    defaults: dict[str, str | None] = {
        "bioguide_id": "D000001",
        "full_name": "Jane Doe",
        "chamber": "house",
        "party": "D",
        "state": "CA",
        "district": "12",
    }
    defaults.update(overrides)
    return Politician(**defaults)


def _transaction(**overrides: object) -> Transaction:
    defaults: dict[str, object] = {
        "filing_id": "house:1",
        "row_index": 0,
        "owner": "self",
        "asset_description_raw": "Apple Inc.",
        "ticker": "AAPL",
        "tx_type": "purchase",
        "amount_min": 1001,
        "amount_max": 15000,
    }
    defaults.update(overrides)
    return Transaction(**defaults)


def test_describe_filer_uses_politician_party_and_state_when_linked() -> None:
    assert describe_filer("DOE, Jane", _politician()) == "Jane Doe (D-CA)"


def test_describe_filer_falls_back_to_raw_filer_name_when_unlinked() -> None:
    assert describe_filer("DOE, Jane", None) == "DOE, Jane"


def test_describe_filer_omits_dash_when_party_or_state_missing() -> None:
    assert describe_filer("DOE, Jane", _politician(party=None, state=None)) == "Jane Doe"


def test_describe_filer_appends_committees_in_brackets() -> None:
    result = describe_filer("DOE, Jane", _politician(), ["Financial Services", "Agriculture"])

    assert result == "Jane Doe (D-CA) [Financial Services, Agriculture]"


def test_describe_filer_caps_committees_and_reports_remainder() -> None:
    committees = ["A", "B", "C", "D", "E"]

    result = describe_filer("DOE, Jane", _politician(), committees)

    assert result == "Jane Doe (D-CA) [A, B, C, +2 more]"


def test_describe_filer_omits_brackets_without_committees() -> None:
    assert describe_filer("DOE, Jane", _politician(), []) == "Jane Doe (D-CA)"


def test_describe_transaction_formats_buy_with_ticker_amount_and_owner() -> None:
    t = _transaction()

    assert describe_transaction(t) == "BUY AAPL $1,001-$15,000 [self]"


def test_describe_transaction_formats_sale_partial() -> None:
    t = _transaction(tx_type="sale_partial", owner="spouse", amount_min=15001, amount_max=50000)

    assert describe_transaction(t) == "SELL (partial) AAPL $15,001-$50,000 [spouse]"


def test_describe_transaction_falls_back_to_asset_description_without_ticker() -> None:
    t = _transaction(ticker=None, asset_description_raw="US Treasury Note 2.5% 2028")

    assert "US Treasury Note 2.5% 2028" in describe_transaction(t)


def test_describe_transaction_omits_amount_when_missing() -> None:
    # Confirmed live: not every parsed transaction carries a usable amount
    # range -- the message shouldn't render a dangling "$None-$None".
    t = _transaction(amount_min=None, amount_max=None)

    assert describe_transaction(t) == "BUY AAPL [self]"


def test_describe_transaction_omits_owner_bracket_when_missing() -> None:
    t = _transaction(owner=None)

    assert describe_transaction(t) == "BUY AAPL $1,001-$15,000"
