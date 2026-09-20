import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from congress_collector.db import models  # noqa: F401  (registers tables on Base.metadata)
from congress_collector.db.base import SCHEMA, Base
from congress_collector.db.session import psycopg_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", psycopg_url(database_url))

target_metadata = Base.metadata

# Both congress-collector and congress-strategy run independent Alembic
# histories against the same shared `congress` schema. Each repo needs its
# own version table so the two histories don't collide or overwrite each
# other's bookkeeping.
VERSION_TABLE = "alembic_version_collector"


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=VERSION_TABLE,
        version_table_schema=SCHEMA,
        include_schemas=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"prepare_threshold": None},
    )

    with connectable.connect() as connection:
        connection.execute(text(f"SET search_path TO {SCHEMA}, public"))
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=SCHEMA,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
