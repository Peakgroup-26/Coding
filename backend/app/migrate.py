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
    with engine.begin() as conn:
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
