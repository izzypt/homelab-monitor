"""System tasks."""

import logging

import httpx

from app.celery_app import celery_app
from app.config import get_settings

log = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.system.ping_healthcheck")
def ping_healthcheck() -> bool:
    """Dead man's switch: tell healthchecks.io that Colima, Docker and the app are alive.

    Returns False when disabled or when the ping fails; never raises, the next run retries.
    """
    url = get_settings().healthcheck_ping_url
    if not url:
        return False
    try:
        httpx.get(url, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("healthcheck ping failed: %s", exc)
        return False
    return True
