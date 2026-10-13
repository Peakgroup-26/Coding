"""The migrations build exactly the schema the models describe, on SQLite and PostgreSQL."""
from app.db import engine
from app.migrate import schema_diff


def test_migrations_match_models(client):
    # The app ran `alembic upgrade head` on startup (the client fixture starts it).
    with engine.connect() as conn:
        assert schema_diff(conn) == []
