"""Daily data-quality report, sent via Telegram (T18).

A health snapshot of the whole dataset -- not just what changed today --
sent once a day by `.github/workflows/dq-report.yml`, separately from
`collect.yml`'s own 5-minute cadence, so routine variance doesn't spam the
channel. Covers the checks the plan calls for: duplicate transactions,
amendments correctly linked (`is_current`), late filings (> 45 days),
per-chamber parse-success rate, share of paper/scanned filings,
ticker-linking rate, and implausible values.

`compute_metrics` (DB-dependent, verified live against production rather
than unit tested -- there's no database in CI) is kept separate from
`format_report` (pure, unit tested), the same split `ops.silence_check`
uses for its own alerting logic.

"Late filing" uses `notification_date` where the parser captured one
(House) and falls back to the filing's own `filed_date` otherwise (Senate,
which only exposes a filing-level submitted date, not a per-transaction
one -- see `parsers.senate_ptr`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from congress_collector.db.models import DqIssue, Filing, Transaction
from congress_collector.db.session import session_scope
from congress_collector.notify.telegram import send_message

LATE_FILING_THRESHOLD_DAYS = 45


@dataclass(frozen=True)
class ChamberParseStats:
    chamber: str
    parsed: int
    failed: int
    paper: int
    pending: int

    @property
    def attempted(self) -> int:
        return self.parsed + self.failed + self.paper

    @property
    def parse_success_rate(self) -> float | None:
        return self.parsed / self.attempted if self.attempted else None


@dataclass(frozen=True)
class DqMetrics:
    total_transactions: int
    duplicate_groups: int
    broken_amendment_groups: int
    late_filings: int
    late_filing_eligible: int
    chamber_stats: list[ChamberParseStats] = field(default_factory=list)
    scanned_or_paper_filings: int = 0
    classified_filings: int = 0
    ticker_linked: int = 0
    implausible_values: int = 0
    open_dq_issues: int = 0


def compute_metrics(session: Session) -> DqMetrics:
    total_transactions = session.scalar(select(func.count()).select_from(Transaction)) or 0

    duplicate_group_keys = (
        select(Transaction.filing_id)
        .group_by(
            Transaction.filing_id,
            Transaction.owner,
            Transaction.asset_description_raw,
            Transaction.tx_type,
            Transaction.tx_date,
            Transaction.amount_min,
            Transaction.amount_max,
        )
        .having(func.count() > 1)
        .subquery()
    )
    duplicate_groups = session.scalar(select(func.count()).select_from(duplicate_group_keys)) or 0

    broken_amendment_group_keys = (
        select(Transaction.source_transaction_id)
        .where(Transaction.source_transaction_id.is_not(None))
        .group_by(Transaction.source_transaction_id)
        .having(func.sum(case((Transaction.is_current, 1), else_=0)) != 1)
        .subquery()
    )
    broken_amendment_groups = (
        session.scalar(select(func.count()).select_from(broken_amendment_group_keys)) or 0
    )

    effective_notification_date = func.coalesce(Transaction.notification_date, Filing.filed_date)
    late_base = (
        select(func.count())
        .select_from(Transaction)
        .join(Filing, Filing.filing_id == Transaction.filing_id)
        .where(Transaction.tx_date.is_not(None), effective_notification_date.is_not(None))
    )
    late_filing_eligible = session.scalar(late_base) or 0
    late_filings = (
        session.scalar(
            late_base.where(
                (effective_notification_date - Transaction.tx_date) > LATE_FILING_THRESHOLD_DAYS
            )
        )
        or 0
    )

    chamber_rows = session.execute(
        select(Filing.chamber, Filing.parse_status, func.count())
        .where(Filing.filing_type == "P")
        .group_by(Filing.chamber, Filing.parse_status)
    ).all()
    chamber_stats = _build_chamber_stats([(c, s, n) for c, s, n in chamber_rows])

    classified_filings = (
        session.scalar(
            select(func.count())
            .select_from(Filing)
            .where(Filing.filing_type == "P", Filing.format != "unknown")
        )
        or 0
    )
    scanned_or_paper_filings = (
        session.scalar(
            select(func.count())
            .select_from(Filing)
            .where(Filing.filing_type == "P", Filing.format.in_(["scanned", "paper"]))
        )
        or 0
    )

    ticker_linked = (
        session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.instrument_id.is_not(None))
        )
        or 0
    )

    implausible_values = (
        session.scalar(
            select(func.count()).select_from(Transaction).where(_implausible_condition())
        )
        or 0
    )

    open_dq_issues = (
        session.scalar(
            select(func.count()).select_from(DqIssue).where(DqIssue.resolved_at.is_(None))
        )
        or 0
    )

    return DqMetrics(
        total_transactions=total_transactions,
        duplicate_groups=duplicate_groups,
        broken_amendment_groups=broken_amendment_groups,
        late_filings=late_filings,
        late_filing_eligible=late_filing_eligible,
        chamber_stats=chamber_stats,
        scanned_or_paper_filings=scanned_or_paper_filings,
        classified_filings=classified_filings,
        ticker_linked=ticker_linked,
        implausible_values=implausible_values,
        open_dq_issues=open_dq_issues,
    )


def _implausible_condition() -> ColumnElement[bool]:
    amount_range_inverted = (
        Transaction.amount_min.is_not(None)
        & Transaction.amount_max.is_not(None)
        & (Transaction.amount_min > Transaction.amount_max)
    )
    negative_amount = (Transaction.amount_min < 0) | (Transaction.amount_max < 0)
    notified_before_traded = (
        Transaction.notification_date.is_not(None)
        & Transaction.tx_date.is_not(None)
        & (Transaction.notification_date < Transaction.tx_date)
    )
    tx_date_in_future = Transaction.tx_date.is_not(None) & (Transaction.tx_date > date.today())
    non_positive_strike = Transaction.strike.is_not(None) & (Transaction.strike <= 0)
    return (
        amount_range_inverted
        | negative_amount
        | notified_before_traded
        | tx_date_in_future
        | non_positive_strike
    )


def _build_chamber_stats(rows: Sequence[tuple[str, str, int]]) -> list[ChamberParseStats]:
    by_chamber: dict[str, dict[str, int]] = {}
    for chamber, parse_status, count in rows:
        by_chamber.setdefault(chamber, {})[parse_status] = count
    return [
        ChamberParseStats(
            chamber=chamber,
            parsed=counts.get("parsed", 0),
            failed=counts.get("failed", 0),
            paper=counts.get("paper_deferred", 0),
            pending=counts.get("pending", 0),
        )
        for chamber, counts in sorted(by_chamber.items())
    ]


def format_report(metrics: DqMetrics) -> str:
    lines = ["Daily data-quality report", ""]

    lines.append(f"Transactions: {metrics.total_transactions}")

    for stats in metrics.chamber_stats:
        rate = stats.parse_success_rate
        rate_str = f"{rate:.1%}" if rate is not None else "n/a"
        lines.append(
            f"  {stats.chamber}: parse success {rate_str} "
            f"({stats.parsed}/{stats.attempted}, {stats.pending} pending)"
        )

    if metrics.classified_filings:
        paper_rate = metrics.scanned_or_paper_filings / metrics.classified_filings
        lines.append(
            f"Paper/scanned filings: {metrics.scanned_or_paper_filings}"
            f"/{metrics.classified_filings} ({paper_rate:.1%})"
        )

    if metrics.total_transactions:
        ticker_rate = metrics.ticker_linked / metrics.total_transactions
        lines.append(
            f"Ticker-linked: {metrics.ticker_linked}/{metrics.total_transactions} "
            f"({ticker_rate:.1%})"
        )

    if metrics.late_filing_eligible:
        late_rate = metrics.late_filings / metrics.late_filing_eligible
        lines.append(
            f"Late filings (>{LATE_FILING_THRESHOLD_DAYS}d): {metrics.late_filings}"
            f"/{metrics.late_filing_eligible} ({late_rate:.1%})"
        )

    lines.append("")
    lines.append(f"Duplicate transaction groups: {metrics.duplicate_groups}")
    lines.append(f"Broken amendment links: {metrics.broken_amendment_groups}")
    lines.append(f"Implausible values: {metrics.implausible_values}")
    lines.append(f"Open dq_issues: {metrics.open_dq_issues}")

    return "\n".join(lines)


def main() -> None:
    with session_scope() as session:
        metrics = compute_metrics(session)
    send_message(format_report(metrics), category="system")


if __name__ == "__main__":
    main()
