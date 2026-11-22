"""Host heartbeat ingest, reboot detection and host health (README sections 5.2, 5.3).

Database logic only: the API and Celery tasks call these functions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BootEvent, Host, HostHeartbeat, Incident
from app.monitoring import create_alert

STALE_AFTER = timedelta(seconds=90)
DISK_HIGH_PCT = 90.0
DISK_OK_PCT = 85.0  # hysteresis: close the disk incident only once usage drops below this
BOOT_TIME_TOLERANCE = timedelta(seconds=60)  # kern.boottime can shift slightly (NTP)

# macOS "Previous shutdown cause" codes. 5 is a normal shutdown or restart; everything else
# (0 power loss, 3 forced power-off, negative values for panics, thermal or watchdog) is not.
CLEAN_SHUTDOWN_CODES = {5}


@dataclass
class HeartbeatIn:
    collected_at: datetime
    boot_time: datetime
    uptime_s: int
    load_1m: float | None = None
    mem_used_pct: float | None = None
    disk_used_pct: float | None = None
    daemons: dict[str, Any] = field(default_factory=dict)
    os_version: str | None = None
    agent_version: str | None = None
    shutdown_cause: int | None = None


def classify_shutdown(code: int | None) -> str:
    if code is None:
        return "unknown"
    return "clean" if code in CLEAN_SHUTDOWN_CODES else "unexpected"


def ingest(db: Session, host: Host, beats: list[HeartbeatIn], now: datetime) -> list[int]:
    """Store heartbeats (possibly a buffered backlog) and update host state.

    Liveness uses server receive time; history uses the agent's collected_at.
    Returns ids of alerts to send.
    """
    host = db.get(Host, host.id, with_for_update=True)
    beats = sorted(beats, key=lambda b: b.collected_at)
    alert_ids: list[int] = []
    previous_seen = host.last_seen_at

    for beat in beats:
        db.add(
            HostHeartbeat(
                host_id=host.id,
                collected_at=beat.collected_at,
                received_at=now,
                boot_time=beat.boot_time,
                uptime_s=beat.uptime_s,
                load_1m=beat.load_1m,
                mem_used_pct=beat.mem_used_pct,
                disk_used_pct=beat.disk_used_pct,
                daemons=beat.daemons,
            )
        )
        if host.current_boot_time is None:
            host.current_boot_time = beat.boot_time  # first contact: nothing to compare with
        elif abs(beat.boot_time - host.current_boot_time) > BOOT_TIME_TOLERANCE:
            alert_ids += _record_boot(db, host, beat, previous_seen)
            host.current_boot_time = beat.boot_time
        previous_seen = beat.collected_at

    latest = beats[-1]
    host.last_seen_at = now
    host.os_version = latest.os_version or host.os_version
    host.agent_version = latest.agent_version or host.agent_version
    if host.status == "STALE":
        alert_ids += _close_incident(db, host.id, "stale", now, alert_kind="recovered")
    host.status = "UP"
    alert_ids += _evaluate_disk(db, host.id, latest.disk_used_pct, now)
    db.commit()
    return alert_ids


def _record_boot(
    db: Session, host: Host, beat: HeartbeatIn, last_seen_before: datetime | None
) -> list[int]:
    kind = classify_shutdown(beat.shutdown_cause)
    downtime = None
    if last_seen_before is not None and beat.boot_time > last_seen_before:
        downtime = int((beat.boot_time - last_seen_before).total_seconds())
    event = BootEvent(
        host_id=host.id,
        boot_time=beat.boot_time,
        last_seen_before=last_seen_before,
        shutdown_cause_code=beat.shutdown_cause,
        kind=kind,
        downtime_s=downtime,
    )
    db.add(event)
    db.flush()
    if kind == "unexpected":
        return create_alert(db, "unexpected_reboot", boot_event_id=event.id)
    return []


def _open_incident(db: Session, host_id: int, kind: str) -> Incident | None:
    return db.scalar(
        select(Incident).where(
            Incident.host_id == host_id, Incident.kind == kind, Incident.ended_at.is_(None)
        )
    )


def _close_incident(
    db: Session, host_id: int, kind: str, now: datetime, alert_kind: str | None = None
) -> list[int]:
    incident = _open_incident(db, host_id, kind)
    if incident is None:
        return []
    incident.ended_at = now
    if alert_kind:
        return create_alert(db, alert_kind, incident_id=incident.id)
    return []


def _evaluate_disk(db: Session, host_id: int, disk_pct: float | None, now: datetime) -> list[int]:
    if disk_pct is None:
        return []
    if disk_pct > DISK_HIGH_PCT and _open_incident(db, host_id, "disk_high") is None:
        incident = Incident(
            host_id=host_id, kind="disk_high", started_at=now, cause=f"disk {disk_pct:.0f}% full"
        )
        db.add(incident)
        db.flush()
        return create_alert(db, "disk_high", incident_id=incident.id)
    if disk_pct < DISK_OK_PCT:
        _close_incident(db, host_id, "disk_high", now)
    return []


def mark_stale_hosts(db: Session, now: datetime) -> list[int]:
    """Hosts that stopped sending heartbeats: UP -> STALE, one incident and one email."""
    hosts = db.scalars(
        select(Host)
        .where(Host.status == "UP", Host.last_seen_at < now - STALE_AFTER)
        .with_for_update(skip_locked=True)
    ).all()
    alert_ids: list[int] = []
    for host in hosts:
        host.status = "STALE"
        incident = Incident(
            host_id=host.id,
            kind="stale",
            started_at=host.last_seen_at,
            cause=f"no heartbeat since {host.last_seen_at:%Y-%m-%d %H:%M:%S} UTC",
        )
        db.add(incident)
        db.flush()
        alert_ids += create_alert(db, "down", incident_id=incident.id)
    db.commit()
    return alert_ids
