"""Tests for the House PTR word-position parser.

Word coordinates in `_word()` calls are taken verbatim from
`extract_words()` output captured live against real PTR PDFs (DocID
20033751 and 20034201, fetched from a GitHub Actions runner -- this
sandbox's egress proxy blocks the source domain, so the raw PDF bytes
themselves can't be pulled in here for a full pdfplumber-level test).
Rows beyond what was captured (multi-transaction filings, a self-owned
transaction, the wrapped-amount continuation, a skipped Description
block) are constructed by hand using the same verified column x0
convention, and are marked as such below.
"""

from congress_collector.parsers.house_ptr import (
    Word,
    is_electronic,
    parse_ptr_transactions,
)

# Shared header, identical (up to sub-pixel rounding) across both real
# sample filings.
_HEADER = [
    Word("ID", 25.3, 281.4),
    Word("Owner", 65.1, 281.4),
    Word("Asset", 104.1, 281.4),
    Word("Transaction", 262.3, 281.4),
    Word("Date", 326.8, 281.4),
    Word("Notification", 381.6, 281.4),
    Word("Amount", 446.1, 281.4),
    Word("Cap.", 524.8, 281.4),
    Word("Type", 262.3, 292.6),
    Word("Date", 381.6, 292.6),
    Word("Gains", 524.8, 292.6),
    Word(">", 555.2, 292.6),
    Word("$200?", 524.8, 303.9),
]

_FOOTER = [
    Word(
        "* For the complete list of asset type abbreviations, please visit "
        "https://fd.house.gov/reference/asset-type-codes.aspx.",
        21.7,
        900.0,
    )
]


def test_scanned_pdf_has_no_recognizable_headers() -> None:
    assert is_electronic([[]]) is False


def test_electronic_pdf_headers_detected() -> None:
    assert is_electronic([_HEADER]) is True


def test_single_transaction_no_wrap_real_coordinates() -> None:
    # Real DocID 20033751, second transaction: self-... no, spouse-owned,
    # single-line asset description, no amount wrap.
    line = [
        Word("SP", 65.7, 326.0),
        Word("Netflix,", 104.7, 326.0),
        Word("Inc.", 130.0, 326.0),
        Word("-", 150.0, 326.0),
        Word("Common", 160.0, 326.0),
        Word("Stock", 200.0, 326.0),
        Word("(NFLX)", 230.0, 326.0),
        Word("S", 262.2, 326.0),
        Word("12/12/2025", 326.7, 326.0),
        Word("01/06/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    continuation = [Word("[ST]", 104.7, 336.5)]

    pages = [[*_HEADER, *line, *continuation, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.owner == "spouse"
    assert tx.asset_description_raw == "Netflix, Inc. - Common Stock (NFLX) [ST]"
    assert tx.ticker == "NFLX"
    assert tx.asset_type == "ST"
    assert tx.tx_type == "sale_full"
    assert tx.tx_date == "2025-12-12"
    assert tx.notification_date == "2026-01-06"
    assert tx.amount_min == 1001
    assert tx.amount_max == 15000


def test_amount_wraps_to_next_line_real_coordinates() -> None:
    # Real DocID 20033751, first transaction: amount range wraps onto its
    # own line, at the same x0 as the amount column above it.
    line = [
        Word("SP", 65.7, 326.0),
        Word("Ferguson", 104.7, 326.0),
        Word("Enterprises", 144.1, 326.0),
        Word("Inc.", 192.2, 326.0),
        Word("Common", 209.7, 326.0),
        Word("P", 262.2, 326.0),
        Word("12/12/2025", 326.7, 326.0),
        Word("01/06/2026", 381.4, 326.0),
        Word("$15,001", 445.9, 326.0),
        Word("-", 479.6, 326.0),
    ]
    wrapped_continuation = [
        Word("Stock", 104.7, 336.5),
        Word("(FERG)", 144.0, 336.5),
        Word("[ST]", 175.0, 336.5),
        Word("$50,000", 445.9, 336.5),
    ]

    pages = [[*_HEADER, *line, *wrapped_continuation, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.owner == "spouse"
    assert tx.asset_description_raw == "Ferguson Enterprises Inc. Common Stock (FERG) [ST]"
    assert tx.ticker == "FERG"
    assert tx.tx_type == "purchase"
    assert tx.amount_min == 15001
    assert tx.amount_max == 50000


def test_self_owned_partial_sale_real_coordinates() -> None:
    # Real DocID 20034201: no owner-zone word at all (self), "(partial)"
    # marker, and a garbled multi-line Description annotation block that
    # must be skipped without corrupting the next transaction.
    line = [
        Word("Amazon.com,", 103.9, 326.0),
        Word("Inc.", 160.5, 326.0),
        Word("-", 178.0, 326.0),
        Word("Common", 183.5, 326.0),
        Word("Stock", 222.4, 326.0),
        Word("S", 262.2, 326.0),
        Word("(partial)", 269.4, 326.0),
        Word("03/16/2026", 326.7, 326.0),
        Word("03/16/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    asset_continuation = [Word("(AMZN)", 104.7, 336.5), Word("[ST]", 140.0, 336.5)]
    # Real: "D\x00...: The full transaction included the following sales:
    # T - 37.426 shares sold @ ..." wrapping across several plain lines
    # before the blank separator and the next transaction.
    description_start = [
        Word("D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00:", 104.7, 347.0),
        Word("The", 160.0, 347.0),
        Word("full", 180.0, 347.0),
    ]
    description_wrap = [Word("sold", 104.7, 357.5), Word("@", 130.0, 357.5)]
    blank_separator: list[Word] = []

    next_line = [
        Word("Apple", 103.9, 400.0),
        Word("Inc.", 140.0, 400.0),
        Word("S", 262.2, 400.0),
        Word("(partial)", 269.4, 400.0),
        Word("03/16/2026", 326.7, 400.0),
        Word("03/16/2026", 381.4, 400.0),
        Word("$1,001", 445.9, 400.0),
        Word("-", 474.8, 400.0),
        Word("$15,000", 480.4, 400.0),
    ]
    next_continuation = [Word("(AAPL)", 104.7, 410.5), Word("[ST]", 140.0, 410.5)]

    pages = [
        [
            *_HEADER,
            *line,
            *asset_continuation,
            *description_start,
            *description_wrap,
            *blank_separator,
            *next_line,
            *next_continuation,
            *_FOOTER,
        ]
    ]
    results = parse_ptr_transactions(pages)

    assert len(results) == 2

    first = results[0]
    assert first.owner == "self"
    assert first.asset_description_raw == "Amazon.com, Inc. - Common Stock (AMZN) [ST]"
    assert first.tx_type == "sale_partial"
    assert "sold" not in first.asset_description_raw
    assert "full" not in first.asset_description_raw

    second = results[1]
    assert second.owner == "self"
    assert second.asset_description_raw == "Apple Inc. (AAPL) [ST]"
    assert second.tx_type == "sale_partial"


def test_multi_page_filing_resets_header_state() -> None:
    page_one = [*_HEADER]  # header only, no transactions before page break
    page_two_line = [
        Word("SP", 65.7, 326.0),
        Word("Netflix,", 104.7, 326.0),
        Word("Inc.", 130.0, 326.0),
        Word("S", 262.2, 326.0),
        Word("12/12/2025", 326.7, 326.0),
        Word("01/06/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    page_two = [*_HEADER, *page_two_line, *_FOOTER]

    results = parse_ptr_transactions([page_one, page_two])

    assert len(results) == 1
    assert results[0].asset_description_raw == "Netflix, Inc."


def test_structured_option_description_real_coordinates() -> None:
    # Real DocID 20034305, row 7: "D...: Call options; Strike price $320;
    # Expires 06/18/2026" -- confirmed live via a GitHub Actions runner
    # (T15 diagnostic) against a real House PTR PDF.
    line = [
        Word("JT", 65.7, 326.0),
        Word("Microsoft", 104.7, 326.0),
        Word("Corporation", 160.0, 326.0),
        Word("-", 220.0, 326.0),
        Word("Common", 225.0, 326.0),
        Word("P", 262.2, 326.0),
        Word("03/25/2026", 326.7, 326.0),
        Word("04/07/2026", 381.4, 326.0),
        Word("$500,001", 445.9, 326.0),
        Word("-", 479.6, 326.0),
    ]
    asset_continuation = [
        Word("Stock", 104.7, 336.5),
        Word("(MSFT)", 140.0, 336.5),
        Word("[OP]", 175.0, 336.5),
        Word("$1,000,000", 445.9, 336.5),
    ]
    filing_status = [
        Word("F\x00\x00\x00\x00\x00", 104.7, 347.0),
        Word("S\x00\x00\x00\x00\x00:", 130.0, 347.0),
        Word("New", 150.0, 347.0),
    ]
    sub_holding = [
        Word("S\x00\x00\x00\x00\x00\x00\x00\x00\x00", 104.7, 357.5),
        Word("O\x00:", 130.0, 357.5),
        Word("Morgan", 140.0, 357.5),
        Word("Stanley", 170.0, 357.5),
    ]
    description = [
        Word("D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00:", 104.7, 368.0),
        Word("Call", 130.0, 368.0),
        Word("options;", 155.0, 368.0),
        Word("Strike", 190.0, 368.0),
        Word("price", 215.0, 368.0),
        Word("$320;", 240.0, 368.0),
        Word("Expires", 265.0, 368.0),
        Word("06/18/2026", 295.0, 368.0),
    ]

    pages = [
        [
            *_HEADER,
            *line,
            *asset_continuation,
            *filing_status,
            *sub_holding,
            *description,
            *_FOOTER,
        ]
    ]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.asset_type == "OP"
    assert tx.option_type == "call"
    assert tx.strike == 320.0
    assert tx.expiry == "2026-06-18"
    assert "Strike" not in tx.asset_description_raw


def test_informal_option_description_has_no_strike_or_expiry() -> None:
    # Real DocID 20035024, row 5: "D...: 10 puts at $11.80" -- the price
    # is the premium paid per contract, not a strike, so only option_type
    # should come out of this style.
    line = [
        Word("Meta", 104.7, 326.0),
        Word("Platforms,", 140.0, 326.0),
        Word("Inc.", 200.0, 326.0),
        Word("P", 262.2, 326.0),
        Word("04/28/2026", 326.7, 326.0),
        Word("04/28/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    asset_continuation = [
        Word("Common", 104.7, 336.5),
        Word("Stock", 140.0, 336.5),
        Word("(META)", 170.0, 336.5),
        Word("[OP]", 205.0, 336.5),
    ]
    description = [
        Word("D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00:", 104.7, 347.0),
        Word("10", 130.0, 347.0),
        Word("puts", 145.0, 347.0),
        Word("at", 170.0, 347.0),
        Word("$11.80", 185.0, 347.0),
    ]

    pages = [[*_HEADER, *line, *asset_continuation, *description, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.asset_type == "OP"
    assert tx.option_type == "put"
    assert tx.strike is None
    assert tx.expiry is None


def test_non_option_description_is_not_parsed_for_option_details() -> None:
    # A stray "D..." annotation on a non-option row (e.g. a free-text
    # comment) should never populate option_type/strike/expiry.
    line = [
        Word("Invesco", 104.7, 326.0),
        Word("QQQ", 140.0, 326.0),
        Word("Trust", 165.0, 326.0),
        Word("(QQQ)", 190.0, 326.0),
        Word("[OT]", 225.0, 326.0),
        Word("S", 262.2, 326.0),
        Word("06/01/2026", 326.7, 326.0),
        Word("06/01/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    description = [
        Word("D\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00:", 104.7, 336.5),
        Word("FAS", 130.0, 336.5),
        Word("is", 155.0, 336.5),
        Word("an", 170.0, 336.5),
        Word("ETF", 185.0, 336.5),
    ]

    pages = [[*_HEADER, *line, *description, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.asset_type == "OT"
    assert tx.option_type is None
    assert tx.strike is None
    assert tx.expiry is None


def test_source_transaction_id_captured_real_coordinates() -> None:
    # Real DocID 20035035: an amended row, "ID" column value 2000135564 at
    # x0=25.2 -- confirmed live via a GitHub Actions runner (T16
    # diagnostic) against a real House PTR PDF. This is the persistent
    # per-transaction identifier T16's amendment linking keys off.
    line = [
        Word("2000135564", 25.2, 326.0),
        Word("JT", 81.4, 326.0),
        Word("3M", 120.4, 326.0),
        Word("Company", 135.9, 326.0),
        Word("Common", 176.1, 326.0),
        Word("Stock", 214.9, 326.0),
        Word("P", 267.4, 326.0),
        Word("03/15/2025", 331.9, 326.0),
        Word("04/03/2025", 388.2, 326.0),
        Word("$1,001", 452.7, 326.0),
        Word("-", 481.6, 326.0),
        Word("$15,000", 487.1, 326.0),
    ]
    continuation = [Word("(MMM)", 120.4, 336.5), Word("[ST]", 154.4, 336.5)]

    pages = [[*_HEADER, *line, *continuation, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    tx = results[0]
    assert tx.source_transaction_id == "2000135564"
    assert tx.owner == "joint"
    assert tx.ticker == "MMM"


def test_no_id_word_leaves_source_transaction_id_none() -> None:
    # This is the common case, not an edge case: confirmed live (T16
    # diagnostic + a production backfill) that the ID column only
    # appears on rows involved in an amendment -- an ordinary row has
    # nothing there at all, and this shouldn't crash or fabricate a
    # value for it.
    line = [
        Word("SP", 65.7, 326.0),
        Word("Netflix,", 104.7, 326.0),
        Word("Inc.", 130.0, 326.0),
        Word("S", 262.2, 326.0),
        Word("12/12/2025", 326.7, 326.0),
        Word("01/06/2026", 381.4, 326.0),
        Word("$1,001", 445.9, 326.0),
        Word("-", 474.8, 326.0),
        Word("$15,000", 480.4, 326.0),
    ]
    pages = [[*_HEADER, *line, *_FOOTER]]
    results = parse_ptr_transactions(pages)

    assert len(results) == 1
    assert results[0].source_transaction_id is None


def test_line_without_a_tx_type_code_never_starts_a_transaction() -> None:
    # A lone letter in the tx_type zone that isn't P/S/E (e.g. a stray
    # word) must not be mistaken for a new row.
    line = [
        Word("Some", 104.7, 326.0),
        Word("Asset", 130.0, 326.0),
        Word("X", 262.2, 326.0),
    ]
    pages = [[*_HEADER, *line, *_FOOTER]]
    assert parse_ptr_transactions(pages) == []
