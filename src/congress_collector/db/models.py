"""SQLAlchemy models for the congress-collector-owned tables.

These mirror the DDL in ``alembic/versions/20260919_0001_core_schema.py``
exactly. Keep both in sync by hand: there is no live database available in
CI to run autogenerate against.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from congress_collector.db.base import Base

_GEN_UUID = text("extensions.gen_random_uuid()")


class Politician(Base):
    __tablename__ = "politicians"

    bioguide_id: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    chamber: Mapped[str] = mapped_column(Text, nullable=False)
    party: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PoliticianTerm(Base):
    __tablename__ = "politician_terms"

    term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    bioguide_id: Mapped[str] = mapped_column(
        Text, ForeignKey("congress.politicians.bioguide_id"), nullable=False
    )
    chamber: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    party: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PoliticianOverride(Base):
    __tablename__ = "politician_overrides"
    __table_args__ = (UniqueConstraint("chamber", "filer_name"),)

    override_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    chamber: Mapped[str] = mapped_column(Text, nullable=False)
    filer_name: Mapped[str] = mapped_column(Text, nullable=False)
    bioguide_id: Mapped[str] = mapped_column(
        Text, ForeignKey("congress.politicians.bioguide_id"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    primary_ticker: Mapped[str | None] = mapped_column(Text)
    cik: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TickerMap(Base):
    __tablename__ = "ticker_map"

    ticker_map_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("congress.instruments.instrument_id"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="sec")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Filing(Base):
    __tablename__ = "filings"

    filing_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chamber: Mapped[str] = mapped_column(Text, nullable=False)
    filer_name: Mapped[str] = mapped_column(Text, nullable=False)
    bioguide_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("congress.politicians.bioguide_id")
    )
    filing_type: Mapped[str] = mapped_column(Text, nullable=False)
    filed_date: Mapped[date | None] = mapped_column(Date)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_precision_s: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="official")
    raw_object_key: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str | None] = mapped_column(Text)
    supersedes_filing_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("congress.filings.filing_id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("filing_id", "row_index"),)

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    filing_id: Mapped[str] = mapped_column(
        Text, ForeignKey("congress.filings.filing_id"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text)
    asset_description_raw: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    cik: Mapped[str | None] = mapped_column(Text)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("congress.instruments.instrument_id")
    )
    option_type: Mapped[str | None] = mapped_column(Text)
    strike: Mapped[float | None] = mapped_column(Numeric)
    expiry: Mapped[date | None] = mapped_column(Date)
    underlying_ticker: Mapped[str | None] = mapped_column(Text)
    tx_type: Mapped[str] = mapped_column(Text, nullable=False)
    tx_date: Mapped[date | None] = mapped_column(Date)
    notification_date: Mapped[date | None] = mapped_column(Date)
    amount_min: Mapped[float | None] = mapped_column(Numeric)
    amount_max: Mapped[float | None] = mapped_column(Numeric)
    filing_delay_days: Mapped[int | None] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    source_transaction_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    chamber: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    new_filings_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)


class DqIssue(Base):
    __tablename__ = "dq_issues"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=_GEN_UUID
    )
    filing_id: Mapped[str | None] = mapped_column(Text, ForeignKey("congress.filings.filing_id"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("congress.transactions.transaction_id")
    )
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
