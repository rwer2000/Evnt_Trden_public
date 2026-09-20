from congress_collector.db import models  # noqa: F401  (registers tables on Base.metadata)
from congress_collector.db.base import SCHEMA, Base

EXPECTED_TABLES = {
    "politicians",
    "politician_terms",
    "instruments",
    "ticker_map",
    "filings",
    "transactions",
    "scrape_runs",
    "dq_issues",
}


def test_schema_is_congress() -> None:
    assert Base.metadata.schema == SCHEMA


def test_all_core_tables_registered() -> None:
    table_names = {table.name for table in Base.metadata.tables.values()}
    assert table_names >= EXPECTED_TABLES
