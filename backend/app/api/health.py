"""Liveness and readiness probes (internal: used by Docker healthchecks)."""

import logging
from collections.abc import Callable

import redis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

log = logging.getLogger(__name__)
router = APIRouter(tags=["ops"])


def check_postgres() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def check_redis() -> None:
    client = redis.Redis.from_url(get_settings().redis_url(), socket_timeout=2)
    try:
        client.ping()
    finally:
        client.close()


def get_dependency_checks() -> dict[str, Callable[[], None]]:
    return {"postgres": check_postgres, "redis": check_redis}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """The process is alive. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(
    response: Response,
    checks: dict[str, Callable[[], None]] = Depends(get_dependency_checks),  # noqa: B008
) -> dict[str, object]:
    """Postgres and Redis are reachable."""
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:  # report any dependency failure as not ready
            log.warning("readiness check failed: %s: %s", name, exc)
            results[name] = "error"
    ready = all(v == "ok" for v in results.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready else "error", "checks": results}
