"""Celery application: queues, routing and the beat schedule."""

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.config import get_settings
from app.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "homelab_monitor",
    broker=settings.redis_url(db=1),
    include=["app.tasks.system", "app.tasks.monitoring"],
)

celery_app.conf.update(
    # JSON only, never pickle.
    task_serializer="json",
    accept_content=["json"],
    # Outcomes are written to Postgres, so no result backend.
    task_ignore_result=True,
    timezone=settings.timezone,
    enable_utc=True,
    # Two queues: I/O-bound checks vs. everything else (see README section 8).
    task_queues=(Queue("default"), Queue("checks")),
    task_default_queue="default",
    task_routes={"app.tasks.checks.*": {"queue": "checks"}},
    task_time_limit=60,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "schedule-due-checks": {
            "task": "app.tasks.monitoring.schedule_due_checks",
            "schedule": 15.0,
        },
        "check-tls-expiry": {
            "task": "app.tasks.monitoring.check_tls_expiry",
            "schedule": crontab(hour=9, minute=0),
        },
        "ping-healthcheck": {
            "task": "app.tasks.system.ping_healthcheck",
            "schedule": 60.0,
        },
    },
)
