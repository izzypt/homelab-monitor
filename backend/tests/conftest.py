"""Test configuration.

Database and Redis tests need real PostgreSQL 16 and Redis. CI provides them as service
containers; locally, point POSTGRES_* / REDIS_* at your own instances (e.g. `make dev`).
"""

import os

# Must run before any app module is imported: settings and the engine are built at import time.
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "homelab_monitor_test")
os.environ.setdefault("POSTGRES_USER", "homelab_monitor")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "test")
os.environ["SESSION_COOKIE_SECURE"] = "false"  # the test client talks plain http

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.security import get_redis  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_db():
    """Apply the real Alembic migrations once, so tests also cover the migration itself."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(migrated_db):
    session = SessionLocal()
    yield session
    session.close()
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def redis_client():
    client = get_redis()
    client.flushdb()
    yield client
    client.flushdb()
