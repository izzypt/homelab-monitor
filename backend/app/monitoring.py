"""Monitor scheduling, state machine, incidents and alert records (README sections 5.1, 5.5).

Database logic only: Celery tasks in app.tasks call these functions.
"""

import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.checks import CheckOutcome
from app.models import Alert, CheckResult, Incident, Monitor

log = logging.getLogger(__name__)

MAX_CATCH_UP_JITTER_S = 10


@dataclass(frozen=True)
class DueCheck:
    monitor_id: int
    countdown_s: float  # jitter: spread checks out after downtime
    expires_s: int  # drop the check if the worker can't start it within one interval


def claim_due_monitors(db: Session, now: datetime, limit: int = 500) -> list[DueCheck]:
    """Atomically claim monitors that are due and push their next_check_at forward.

    FOR UPDATE SKIP LOCKED makes two concurrent schedulers claim disjoint sets.
    """
    rows = db.execute(
        select(Monitor.id, Monitor.interval_s, Monitor.next_check_at)
        .where(Monitor.enabled.is_(True), Monitor.next_check_at <= now)
        .order_by(Monitor.next_check_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    due: list[DueCheck] = []
    for monitor_id, interval_s, next_check_at in rows:
        db.execute(
            update(Monitor)
            .where(Monitor.id == monitor_id)
            .values(next_check_at=now + timedelta(seconds=interval_s))
        )
        overdue_s = (now - next_check_at).total_seconds()
        countdown = random.uniform(0, MAX_CATCH_UP_JITTER_S) if overdue_s > interval_s else 0  # noqa: S311
        due.append(DueCheck(monitor_id, countdown, interval_s))
    db.commit()
    return due


def record_result(db: Session, monitor_id: int, outcome: CheckOutcome, now: datetime) -> list[int]:
    """Store a result, advance the monitor's state machine, and return new alert ids to send."""
    monitor = db.get(Monitor, monitor_id, with_for_update=True)
    if monitor is None:  # deleted while the check was in flight
        db.rollback()
        return []

    db.add(
        CheckResult(
            monitor_id=monitor.id,
            checked_at=now,
            ok=outcome.ok,
            status_code=outcome.status_code,
            latency_ms=outcome.latency_ms,
            error=outcome.error,
        )
    )
    monitor.last_checked_at = now
    alert_ids: list[int] = []

    if outcome.ok:
        monitor.consecutive_failures = 0
        if monitor.state == "DOWN":
            incident = _open_incident(db, monitor.id, "down")
            if incident is not None:
                incident.ended_at = now
                alert_ids += create_alert(db, "recovered", incident_id=incident.id)
        monitor.state = "UP"
    else:
        monitor.consecutive_failures += 1
        if monitor.state != "DOWN" and monitor.consecutive_failures >= monitor.failure_threshold:
            monitor.state = "DOWN"
            incident = Incident(
                monitor_id=monitor.id, kind="down", started_at=now, cause=outcome.error
            )
            db.add(incident)
            db.flush()
            alert_ids += create_alert(db, "down", incident_id=incident.id)

    db.commit()
    return alert_ids


def record_tls_expiry(
    db: Session, monitor_id: int, expires_at: datetime, now: datetime, warning_days: int
) -> list[int]:
    """Update tls_expires_at; open a tls_expiring incident (one email) or close it on renewal."""
    monitor = db.get(Monitor, monitor_id, with_for_update=True)
    if monitor is None:
        db.rollback()
        return []
    monitor.tls_expires_at = expires_at
    incident = _open_incident(db, monitor.id, "tls_expiring")
    alert_ids: list[int] = []
    expiring = expires_at - now <= timedelta(days=warning_days)
    if expiring and incident is None:
        incident = Incident(
            monitor_id=monitor.id,
            kind="tls_expiring",
            started_at=now,
            cause=f"certificate expires {expires_at:%Y-%m-%d}",
        )
        db.add(incident)
        db.flush()
        alert_ids += create_alert(db, "tls_expiring", incident_id=incident.id)
    elif not expiring and incident is not None:
        incident.ended_at = now  # renewed
    db.commit()
    return alert_ids


def _open_incident(db: Session, monitor_id: int, kind: str) -> Incident | None:
    return db.scalar(
        select(Incident)
        .where(
            Incident.monitor_id == monitor_id,
            Incident.kind == kind,
            Incident.ended_at.is_(None),
        )
        .order_by(Incident.started_at.desc())
        .limit(1)
    )


def create_alert(
    db: Session, kind: str, *, incident_id: int | None = None, boot_event_id: int | None = None
) -> list[int]:
    """Insert an alert unless one already exists for this subject and kind (idempotent)."""
    constraint = "uq_alerts_incident_kind" if incident_id else "uq_alerts_boot_event_kind"
    alert_id = db.scalar(
        insert(Alert)
        .values(incident_id=incident_id, boot_event_id=boot_event_id, kind=kind)
        .on_conflict_do_nothing(constraint=constraint)
        .returning(Alert.id)
    )
    return [alert_id] if alert_id is not None else []


def utcnow() -> datetime:
    return datetime.now(UTC)
