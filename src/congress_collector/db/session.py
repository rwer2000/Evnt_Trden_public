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
    engine = create_engine(psycopg_url(os.environ["DATABASE_URL"]), pool_pre_ping=True)

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
