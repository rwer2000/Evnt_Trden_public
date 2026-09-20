"""SQLAlchemy engine/session setup, reading DATABASE_URL from the environment."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from congress_collector.db.base import SCHEMA


def psycopg_url(database_url: str) -> str:
    """A bare `postgresql://` URL makes SQLAlchemy default to the
    (uninstalled) psycopg2 driver; we depend on psycopg 3 instead."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # We connect through Supabase's Supavisor pooler in transaction mode, where a
    # pooled connection can be handed to a different logical session between
    # statements. psycopg's default server-side prepared-statement cache assumes a
    # stable session and raises DuplicatePreparedStatement under that churn, so it
    # must be disabled here.
    # A statement_timeout turns a stuck/runaway query (e.g. a pooler silently
    # dropping a long-running statement's connection, as observed once with
    # a large bulk insert) into a clear, fast Postgres error instead of a
    # hang with no diagnosable cause.
    engine = create_engine(
        psycopg_url(os.environ["DATABASE_URL"]),
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None, "options": "-c statement_timeout=60000"},
    )

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET search_path TO {SCHEMA}, public")
        cursor.close()

    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    session = sessionmaker(bind=get_engine())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
