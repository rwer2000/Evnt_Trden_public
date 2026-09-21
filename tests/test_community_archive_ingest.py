from datetime import date

from congress_collector.ingest.community_archive import dedup_key_for
from congress_collector.sources.community_archive import HOUSE_SOURCE, CommunityRecord


def _record(**overrides: object) -> CommunityRecord:
    base = dict(
        source=HOUSE_SOURCE,
        chamber="house",
        external_filing_id="house:20035471",
        filer_name="David J. Taylor",
        ticker="PG",
        asset_description="Procter & Gamble Company",
        asset_type="Stock",
        tx_type="Purchase",
        owner="Self",
        tx_date=date(2026, 9, 8),
        disclosure_date=date(2026, 9, 17),
        amount_min=1001.0,
        amount_max=15000.0,
    )
    base.update(overrides)
    return CommunityRecord(**base)  # type: ignore[arg-type]


def test_dedup_key_is_stable_across_calls() -> None:
    record = _record()
    assert dedup_key_for(record) == dedup_key_for(record)


def test_dedup_key_differs_for_different_transactions() -> None:
    a = _record(ticker="PG")
    b = _record(ticker="AAPL")
    assert dedup_key_for(a) != dedup_key_for(b)


def test_dedup_key_differs_when_amount_differs() -> None:
    a = _record(amount_min=1001.0, amount_max=15000.0)
    b = _record(amount_min=15001.0, amount_max=50000.0)
    assert dedup_key_for(a) != dedup_key_for(b)


def test_dedup_key_same_for_identical_reimport() -> None:
    # Re-importing the same source snapshot must produce the same key,
    # since neither dataset gives us a stable per-row ID to dedupe on.
    a = _record()
    b = _record()
    assert dedup_key_for(a) == dedup_key_for(b)
