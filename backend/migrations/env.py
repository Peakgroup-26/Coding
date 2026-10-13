"""Alembic environment: uses the app's DATABASE_URL and models."""
from alembic import context

from app import models
from app.db import Base, engine

assert models  # imported for its side effect: registers every table on Base.metadata
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        _run(connectable)
        return
    with engine.connect() as connection:
        _run(connection)


def _run(connection):
    # render_as_batch lets ALTER TABLE work on SQLite as well as PostgreSQL.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
