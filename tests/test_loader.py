"""Tests for the database loader.

These hit a real PostgreSQL instance (via docker compose), so they're
integration tests. They're skipped automatically if the DB isn't reachable.
"""
import pytest
from sqlalchemy import create_engine, text

from app.core.config import config


def _db_available() -> bool:
    try:
        engine = create_engine(config.postgres_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="PostgreSQL not reachable")
def test_db_has_expected_tables() -> None:
    engine = create_engine(config.postgres_url)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        )
        tables = {row[0] for row in result}
    assert {"raw_logs", "log_templates", "incidents"} <= tables