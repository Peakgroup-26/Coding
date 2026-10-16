"""Bring the database schema up to date on startup (Alembic)."""
import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from .db import Base

log = logging.getLogger(__name__)
INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def schema_diff(connection) -> list:
    """Differences between the live database and the models (empty when they match)."""
    from . import models

    assert models  # imported for its side effect: registers every table on Base.metadata

    ctx = MigrationContext.configure(connection, opts={"compare_type": True, "render_as_batch": True})
    return compare_metadata(ctx, Base.metadata)


def migrate(engine) -> None:
    cfg = Config(str(INI))
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as conn:
        if sqlite:
            # SQLite changes a column by rebuilding its table; with foreign keys switched on, dropping the old copy of a table
            # others point at (users, jobs) fails once there's data. Off for the migration (outside the transaction, as SQLite
            # requires), then every foreign key is checked before it's switched back on.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        with conn.begin():
            cfg.attributes["connection"] = conn
            tables = set(inspect(conn).get_table_names())
            if tables and "alembic_version" not in tables:
                # A database made before migrations existed. Adopt it only if it already matches.
                diff = schema_diff(conn)
                if diff:
                    raise RuntimeError(
                        "This database was created before migrations were added and doesn't match the current schema "
                        f"({len(diff)} difference(s)). For a development database, delete it (backend/data/) and restart.")
                log.info("Existing database matches the current schema; recording it as up to date.")
                command.stamp(cfg, "head")
            else:
                command.upgrade(cfg, "head")
            if sqlite:
                broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"The migration left {len(broken)} broken links between tables, e.g. {broken[0]}")
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
