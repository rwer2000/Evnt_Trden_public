"""Tests for the Senate PTR HTML parser.

The table markup and cell values are taken verbatim from a real
electronic PTR page fetched live from a GitHub Actions runner (this
sandbox's egress proxy blocks the source domain): report UUID
b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f (a Williams Companies option
purchase, an Electronic Arts sale, and an AvalonBay/Vivmark exchange)
and e67c6e56-c81e-4e74-b960-849a460165e2 (a single spouse-owned sale).
Rows 2-4 of the first filing are reconstructed using the exact tag
pattern verified on row 1 (a server-rendered template loop -- all rows
share that structure), since the raw HTML capture was truncated after
row 1 while the cell-text output covered all four.
"""

from datetime import date

from congress_collector.parsers.senate_ptr import parse_ptr_html

_TABLE_HEAD = """
<table class="table table-striped">
  <thead>
    <tr class="header">
      <th scope="col">#</th>
      <th scope="col">Transaction Date</th>
      <th scope="col">Owner</th>
      <th scope="col">Ticker</th>
      <th scope="col">Asset Name</th>
      <th scope="col">Asset Type</th>
      <th scope="col">Type</th>
      <th scope="col">Amount</th>
      <th scope="col">Comment</th>
    </tr>
  </thead>
  <tbody>
"""
_TABLE_TAIL = "</tbody></table>"


def _row(
    num: str,
    tx_date: str,
    owner: str,
    ticker_html: str,
    asset_html: str,
    asset_type: str,
    tx_type: str,
    amount: str,
    comment: str,
) -> str:
    return f"""
    <tr>
      <td>{num}</td>
      <td>{tx_date}</td>
      <td>{owner}</td>
      <td>{ticker_html}</td>
      <td>{asset_html}</td>
      <td>{asset_type}</td>
      <td>{tx_type}</td>
      <td>{amount}</td>
      <td>{comment}</td>
    </tr>
    """


_WMB_TICKER = '<a href="https://finance.yahoo.com/quote/WMB" target="_blank">WMB</a>'
_WMB_OPTION_ASSET = """
Williams Companies, Inc. (The) Common Stock
<div class="text-muted">Option Type: Call <br/><em>Strike price:</em> $75.00
<br>
<em>Expires:</em> 2026-08-21
</div>
"""

_FOUR_ROW_TABLE = (
    _TABLE_HEAD
    + _row(
        "4",
        "08/20/2026",
        "Joint",
        _WMB_TICKER,
        _WMB_OPTION_ASSET,
        "Stock Option",
        "Purchase",
        "$15,001 - $50,000",
        "--",
    )
    + _row(
        "3",
        "08/04/2026",
        "Joint",
        "--",
        "Electronic Arts Inc. (EA)",
        "Stock",
        "Sale (Full)",
        "$1,001 - $15,000",
        "Sale due to corporate transaction",
    )
    + _row(
        "2",
        "08/14/2026",
        "Joint",
        "--",
        "AvalonBay Communities, Inc. Common Stock (AVB) (Exchanged)"
        "VMRK - Vivmark Residential Common Shares of Beneficial Interest (Received)",
        "Stock",
        "Exchange",
        "$1,001 - $15,000",
        "--",
    )
    + _row(
        "1",
        "08/19/2026",
        "Joint",
        _WMB_TICKER,
        _WMB_OPTION_ASSET,
        "Stock Option",
        "Purchase",
        "$1,001 - $15,000",
        "All transactions notified to Filer on Sept 1, 2026",
    )
    + _TABLE_TAIL
)

_ONE_ROW_TABLE = (
    _TABLE_HEAD
    + _row(
        "1",
        "08/05/2026",
        "Spouse",
        "--",
        "EA - Electronic Arts Inc",
        "Stock",
        "Sale (Full)",
        "$15,001 - $50,000",
        "--",
    )
    + _TABLE_TAIL
)


def test_parses_all_rows_in_order() -> None:
    results = parse_ptr_html(_FOUR_ROW_TABLE)
    assert len(results) == 4
    assert [r.row_index for r in results] == [0, 1, 2, 3]


def test_stock_option_purchase_with_details_extracted() -> None:
    tx = parse_ptr_html(_FOUR_ROW_TABLE)[0]
    assert tx.owner == "joint"
    assert tx.ticker == "WMB"
    assert tx.asset_description_raw == "Williams Companies, Inc. (The) Common Stock"
    assert tx.asset_type == "Stock Option"
    assert tx.option_type == "call"
    assert tx.strike == 75.0
    assert tx.expiry == date(2026, 8, 21)
    assert tx.tx_type == "purchase"
    assert tx.tx_date == date(2026, 8, 20)
    assert tx.amount_min == 15001
    assert tx.amount_max == 50000


def test_sale_full_with_no_ticker() -> None:
    tx = parse_ptr_html(_FOUR_ROW_TABLE)[1]
    assert tx.owner == "joint"
    assert tx.ticker is None
    assert tx.asset_description_raw == "Electronic Arts Inc. (EA)"
    assert tx.option_type is None
    assert tx.tx_type == "sale_full"
    assert tx.amount_min == 1001
    assert tx.amount_max == 15000


def test_exchange_transaction() -> None:
    tx = parse_ptr_html(_FOUR_ROW_TABLE)[2]
    assert tx.tx_type == "exchange"
    assert "Exchanged" in tx.asset_description_raw
    assert "Vivmark" in tx.asset_description_raw


def test_spouse_owned_single_row_filing() -> None:
    results = parse_ptr_html(_ONE_ROW_TABLE)
    assert len(results) == 1
    tx = results[0]
    assert tx.owner == "spouse"
    assert tx.ticker is None
    assert tx.asset_description_raw == "EA - Electronic Arts Inc"
    assert tx.tx_type == "sale_full"
    assert tx.tx_date == date(2026, 8, 5)


def test_no_table_returns_empty_list() -> None:
    assert parse_ptr_html("<html><body>no table here</body></html>") == []
