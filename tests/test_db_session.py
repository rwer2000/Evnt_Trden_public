from congress_collector.db.session import psycopg_url


def test_bare_postgresql_url_gets_psycopg_driver() -> None:
    url = psycopg_url("postgresql://user:pass@host:5432/db")
    assert url == "postgresql+psycopg://user:pass@host:5432/db"


def test_url_with_explicit_driver_is_left_alone() -> None:
    url = "postgresql+psycopg://user:pass@host:5432/db"
    assert psycopg_url(url) == url


def test_url_with_a_different_driver_is_left_alone() -> None:
    url = "postgresql+asyncpg://user:pass@host:5432/db"
    assert psycopg_url(url) == url
