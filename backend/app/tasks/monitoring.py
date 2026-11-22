"""Monitor tasks (README section 8)."""

import logging
import smtplib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app import alerts, checks, containers, hosts, maintenance, monitoring
from app.celery_app import celery_app
from app.config import get_settings
from app.db import SessionLocal
from app.models import Alert, Host, Monitor
from app.security import get_redis

log = logging.getLogger(__name__)

SCHEDULER_LOCK = "lock:schedule_due_checks"
NETWORK_OUTAGE_KEY = "network:outage"
NETWORK_FAILURES_KEY = "network:failures"
NETWORK_FAILURE_THRESHOLD = 2


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
    suppress = bool(get_redis().exists(NETWORK_OUTAGE_KEY))
    with SessionLocal() as db:
        alert_ids = monitoring.record_result(
            db, monitor_id, outcome, monitoring.utcnow(), suppress_alerts=suppress
        )
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


def _docker_host(db) -> Host | None:
    return db.scalar(select(Host).where(Host.name == get_settings().docker_host_name))


@celery_app.task(name="app.tasks.monitoring.snapshot_containers")
def snapshot_containers() -> int:
    settings = get_settings()
    try:
        infos = containers.parse_containers(containers.fetch_containers(settings.docker_api_url))
    except httpx.HTTPError as exc:
        log.warning("docker API unavailable: %s", exc)
        return 0
    with SessionLocal() as db:
        host = _docker_host(db)
        if host is None:
            log.warning(
                "no host named %r: register it to record containers", settings.docker_host_name
            )
            return 0
        return containers.apply_snapshot(db, host, infos, monitoring.utcnow())


@celery_app.task(name="app.tasks.monitoring.check_network")
def check_network() -> str:
    """Control check: the network is down only if every control target fails, twice in a row."""
    settings = get_settings()
    redis = get_redis()
    outcomes = [checks.check_http(url, {}, 5) for url in settings.network_control_url_list]
    network_ok = not outcomes or any(o.ok for o in outcomes)
    alert_ids: list[int] = []
    with SessionLocal() as db:
        host = _docker_host(db)
        if network_ok:
            redis.delete(NETWORK_FAILURES_KEY)
            if redis.delete(NETWORK_OUTAGE_KEY) and host is not None:
                alert_ids = monitoring.close_network_outage(db, host.id, monitoring.utcnow())
        else:
            failures = redis.incr(NETWORK_FAILURES_KEY)
            redis.expire(NETWORK_FAILURES_KEY, 300)
            if failures >= NETWORK_FAILURE_THRESHOLD:
                redis.set(NETWORK_OUTAGE_KEY, "1", ex=300)  # refreshed every minute while down
                if host is not None:
                    cause = "; ".join(
                        f"{u}: {o.error}"
                        for u, o in zip(settings.network_control_url_list, outcomes, strict=True)
                    )
                    alert_ids = monitoring.open_network_outage(
                        db, host.id, monitoring.utcnow(), cause
                    )
    for alert_id in alert_ids:
        send_alert.delay(alert_id)
    return "ok" if network_ok else "down"


@celery_app.task(name="app.tasks.monitoring.rollup_and_prune")
def rollup_and_prune() -> dict[str, int]:
    settings = get_settings()
    now = monitoring.utcnow()
    yesterday = now.astimezone(ZoneInfo(settings.timezone)).date() - timedelta(days=1)
    with SessionLocal() as db:
        rows = maintenance.rollup_day(db, yesterday, settings.timezone)
        deleted = maintenance.prune(
            db, now, settings.raw_retention_days, settings.summary_retention_days
        )
    log.info("rollup %s: %d rows; pruned %s", yesterday, rows, deleted)
    return {"rollup_rows": rows, **deleted}
