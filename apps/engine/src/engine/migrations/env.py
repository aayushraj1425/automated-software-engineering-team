import asyncio
import sys
from logging.config import fileConfig

from alembic import context

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from engine.config import get_settings
from engine.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Migrations run in the explicit service context: under deny-by-default
    # row-level security (engine/db/rls.py) a data migration would otherwise
    # read and write zero rows. Session-scoped (false), so it lasts for every
    # migration on this connection.
    #
    # This first statement opens the connection's transaction, so alembic's
    # begin_transaction() below joins it rather than owning it — and a joined
    # transaction is never committed on exit. We commit it ourselves once the
    # migrations (and their alembic_version bump) are in; without this the
    # whole upgrade silently rolls back on close (the DDL and the service
    # context stay in one transaction, exactly as RLS needs).
    connection.exec_driver_sql("SELECT set_config('app.service', '1', false)")
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
