"""Monitor tasks (README section 8)."""

import logging
import smtplib
from datetime import UTC, datetime

from sqlalchemy import select

from app import alerts, checks, hosts, monitoring
from app.celery_app import celery_app
from app.config import get_settings
from app.db import SessionLocal
from app.models import Alert, Monitor
from app.security import get_redis

log = logging.getLogger(__name__)

SCHEDULER_LOCK = "lock:schedule_due_checks"


@celery_app.task(name="app.tasks.monitoring.schedule_due_checks")
def schedule_due_checks() -> int:
    # Guard against a second beat started by mistake: only one scheduler run at a time.
    if not get_redis().set(SCHEDULER_LOCK, "1", nx=True, ex=14):
        return 0
    with SessionLocal() as db:
        due = monitoring.claim_due_monitors(db, monitoring.utcnow())
    for item in due:
        run_check.apply_async(
            args=[item.monitor_id], countdown=item.countdown_s, expires=item.expires_s
        )
    return len(due)


@celery_app.task(name="app.tasks.checks.run_check")
def run_check(monitor_id: int) -> None:
    """No Celery retry: a failed check is a result, and the next interval is the retry."""
    with SessionLocal() as db:
        monitor = db.get(Monitor, monitor_id)
        if monitor is None or not monitor.enabled:
            return
        kind, target, config, timeout = (
            monitor.type,
            monitor.target,
            dict(monitor.config),
            monitor.timeout_s,
        )
    outcome = checks.run(kind, target, config, timeout)  # no DB connection held during I/O
    with SessionLocal() as db:
        alert_ids = monitoring.record_result(db, monitor_id, outcome, monitoring.utcnow())
    for alert_id in alert_ids:
        send_alert.delay(alert_id)


@celery_app.task(
    name="app.tasks.monitoring.send_alert",
    bind=True,
    acks_late=True,
    autoretry_for=(smtplib.SMTPException, OSError),
    retry_backoff=30,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=10,
)
def send_alert(self, alert_id: int) -> str:
    settings = get_settings()
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id, with_for_update=True)
        if alert is None or alert.status == "sent":
            return "skipped"  # idempotent: never send twice
        alert.attempts += 1
        try:
            alerts.send(alerts.compose(db, alert, settings), settings)
        except alerts.AlertingNotConfigured as exc:
            alert.status, alert.last_error = "failed", str(exc)
            db.commit()
            log.warning("alert %s not sent: %s", alert_id, exc)
            return "failed"
        except (smtplib.SMTPException, OSError) as exc:
            alert.last_error = str(exc)[:500]
            if self.request.retries >= self.max_retries:
                alert.status = "failed"
            db.commit()
            raise
        alert.status, alert.sent_at, alert.last_error = "sent", datetime.now(UTC), None
        db.commit()
    return "sent"


@celery_app.task(name="app.tasks.monitoring.check_tls_expiry")
def check_tls_expiry() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        targets = db.execute(
            select(Monitor.id, Monitor.target).where(
                Monitor.enabled.is_(True),
                Monitor.type == "http",
                Monitor.target.startswith("https://"),
            )
        ).all()
    checked = 0
    for monitor_id, target in targets:
        try:
            expires_at = checks.tls_expiry(target)
        except (OSError, ValueError) as exc:
            log.warning("tls expiry check failed monitor=%s: %s", monitor_id, exc)
            continue
        with SessionLocal() as db:
            alert_ids = monitoring.record_tls_expiry(
                db, monitor_id, expires_at, monitoring.utcnow(), settings.tls_warning_days
            )
        for alert_id in alert_ids:
            send_alert.delay(alert_id)
        checked += 1
    return checked


@celery_app.task(name="app.tasks.monitoring.evaluate_hosts")
def evaluate_hosts() -> int:
    with SessionLocal() as db:
        alert_ids = hosts.mark_stale_hosts(db, monitoring.utcnow())
    for alert_id in alert_ids:
        send_alert.delay(alert_id)
    return len(alert_ids)
