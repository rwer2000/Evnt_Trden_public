import uuid
from datetime import date

from congress_collector.ingest.reparse_house_ptr_amounts import StoredRow, plan_filing
from congress_collector.parsers.house_ptr import ParsedTransaction


def _parsed(row_index: int, description: str, **kw: object) -> ParsedTransaction:
    fields: dict[str, object] = {
        "row_index": row_index,
        "owner": "spouse",
        "asset_description_raw": description,
        "ticker": None,
        "asset_type": None,
        "option_type": None,
        "strike": None,
        "expiry": None,
        "tx_type": "purchase",
        "tx_date": "2025-01-14",
        "notification_date": "2025-01-15",
        "amount_min": 1001.0,
        "amount_max": 15000.0,
        "source_transaction_id": None,
    }
    fields.update(kw)
    return ParsedTransaction(**fields)  # type: ignore[arg-type]


def _stored(
    row_index: int, description: str, notification: date | None = date(2025, 1, 15)
) -> StoredRow:
    return StoredRow(uuid.uuid4(), row_index, description, "purchase", "spouse", notification)


def test_same_row_index_and_description_gets_amount() -> None:
    row = _stored(0, "Acme (ACME) [ST]")
    plan = plan_filing(
        [row], [_parsed(0, "Acme (ACME) [ST]", amount_min=2722.5, amount_max=2722.5)]
    )
    (fix,) = plan.fixes
    assert (fix.transaction_id, fix.amount_min, fix.amount_max) == (
        row.transaction_id,
        2722.5,
        2722.5,
    )
    assert fix.tx_date is None and fix.notification_date is None


def test_stale_parse_without_notification_date_also_fixes_dates() -> None:
    row = _stored(0, "Acme (ACME) [ST]", notification=None)
    (fix,) = plan_filing([row], [_parsed(0, "Acme (ACME) [ST]")]).fixes
    assert (fix.tx_date, fix.notification_date) == (date(2025, 1, 14), date(2025, 1, 15))


def test_shifted_row_index_matches_on_unique_description() -> None:
    # A phantom row earlier in the filing shifted the stored row_index.
    row = _stored(3, "Beta Corp (BETA) [ST]")
    parsed = [_parsed(0, "Acme (ACME) [ST]"), _parsed(1, "Beta Corp (BETA) [ST]")]
    (fix,) = plan_filing([row], parsed).fixes
    assert fix.transaction_id == row.transaction_id


def test_ambiguous_description_is_left_unmatched() -> None:
    row = _stored(5, "Beta Corp (BETA) [ST]")
    parsed = [_parsed(0, "Beta Corp (BETA) [ST]"), _parsed(1, "Beta Corp (BETA) [ST]")]
    plan = plan_filing([row], parsed)
    assert plan.fixes == [] and plan.unmatched == 1


def test_phantom_description_row_is_flagged() -> None:
    row = _stored(1, "DESCRIPTION: PUT BABA Nov 19 21 155.0")
    plan = plan_filing([row], [_parsed(0, "Alibaba (BABA) [OP]")])
    assert plan.phantoms == [row.transaction_id] and plan.fixes == []


def test_parse_still_without_amount_is_counted() -> None:
    row = _stored(0, "Acme (ACME) [ST]")
    plan = plan_filing([row], [_parsed(0, "Acme (ACME) [ST]", amount_min=None, amount_max=None)])
    assert plan.fixes == [] and plan.no_amount == 1
