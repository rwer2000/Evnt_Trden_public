from congress_collector.ops.dq_report import ChamberParseStats, DqMetrics, format_report


def test_chamber_parse_success_rate_none_when_nothing_attempted() -> None:
    stats = ChamberParseStats(chamber="house", parsed=0, failed=0, paper=0, pending=5)
    assert stats.attempted == 0
    assert stats.parse_success_rate is None


def test_chamber_parse_success_rate_excludes_pending() -> None:
    stats = ChamberParseStats(chamber="house", parsed=9, failed=1, paper=0, pending=100)
    assert stats.attempted == 10
    assert stats.parse_success_rate == 0.9


def test_format_report_includes_every_metric() -> None:
    metrics = DqMetrics(
        total_transactions=1000,
        duplicate_groups=2,
        broken_amendment_groups=1,
        late_filings=30,
        late_filing_eligible=300,
        chamber_stats=[
            ChamberParseStats(chamber="house", parsed=90, failed=5, paper=5, pending=1),
            ChamberParseStats(chamber="senate", parsed=50, failed=0, paper=0, pending=0),
        ],
        scanned_or_paper_filings=5,
        classified_filings=150,
        ticker_linked=800,
        implausible_values=3,
        open_dq_issues=12,
    )

    report = format_report(metrics)

    assert "Transactions: 1000" in report
    assert "house: parse success 90.0% (90/100, 1 pending)" in report
    assert "senate: parse success 100.0% (50/50, 0 pending)" in report
    assert "Paper/scanned filings: 5/150 (3.3%)" in report
    assert "Ticker-linked: 800/1000 (80.0%)" in report
    assert "Late filings (>45d): 30/300 (10.0%)" in report
    assert "Duplicate transaction groups: 2" in report
    assert "Broken amendment links: 1" in report
    assert "Implausible values: 3" in report
    assert "Open dq_issues: 12" in report


def test_format_report_skips_rate_lines_with_no_eligible_denominator() -> None:
    metrics = DqMetrics(
        total_transactions=0,
        duplicate_groups=0,
        broken_amendment_groups=0,
        late_filings=0,
        late_filing_eligible=0,
    )

    report = format_report(metrics)

    assert "Ticker-linked" not in report
    assert "Late filings" not in report
    assert "Paper/scanned filings" not in report
    assert "Transactions: 0" in report
