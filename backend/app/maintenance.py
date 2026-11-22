"""Daily rollup into daily_uptime and retention pruning (README sections 5.6 and 6)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    BootEvent,
    CheckResult,
    ContainerEvent,
    DailyUptime,
    Host,
    HostHeartbeat,
    Incident,
)

HEARTBEAT_INTERVAL_S = 30


def day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, ZoneInfo(tz))
    return start, start + timedelta(days=1)


def rollup_day(db: Session, day: date, tz: str) -> int:
    """Write (or rewrite) daily_uptime for every monitor and host for one local calendar day."""
    start, end = day_bounds(day, tz)
    rows = 0

    monitor_stats = db.execute(
        select(
            CheckResult.monitor_id,
            func.count(),
            func.coalesce(func.sum(cast(~CheckResult.ok, Integer)), 0),
            func.avg(CheckResult.latency_ms),
        )
        .where(CheckResult.checked_at >= start, CheckResult.checked_at < end)
        .group_by(CheckResult.monitor_id)
    ).all()
    for monitor_id, total, failed, avg_latency in monitor_stats:
        _upsert(
            db,
            "uq_daily_uptime_monitor_day",
            monitor_id=monitor_id,
            day=day,
            uptime_pct=round(100 * (total - failed) / total, 3),
            avg_latency_ms=float(avg_latency) if avg_latency is not None else None,
            checks_total=total,
            checks_failed=failed,
        )
        rows += 1

    # Host uptime = share of the day covered by heartbeats (one expected every 30 s).
    seconds = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()  # 23/25 h on DST days
    expected = int(seconds // HEARTBEAT_INTERVAL_S)
    host_counts = dict(
        db.execute(
            select(HostHeartbeat.host_id, func.count())
            .where(HostHeartbeat.collected_at >= start, HostHeartbeat.collected_at < end)
            .group_by(HostHeartbeat.host_id)
        ).all()
    )
    for host_id in db.scalars(select(Host.id)):
        received = host_counts.get(host_id, 0)
        _upsert(
            db,
            "uq_daily_uptime_host_day",
            host_id=host_id,
            day=day,
            uptime_pct=round(min(100.0, 100 * received / expected), 3),
            avg_latency_ms=None,
            checks_total=expected,
            checks_failed=max(0, expected - received),
        )
        rows += 1
    db.commit()
    return rows


def _upsert(db: Session, constraint: str, **values) -> None:
    update = {
        k: values[k] for k in ("uptime_pct", "avg_latency_ms", "checks_total", "checks_failed")
    }
    db.execute(
        insert(DailyUptime)
        .values(**values)
        .on_conflict_do_update(constraint=constraint, set_=update)
    )


def prune(db: Session, now: datetime, raw_days: int, summary_days: int) -> dict[str, int]:
    """Delete raw data past raw_days; summaries and closed incidents past summary_days."""
    raw_cutoff = now - timedelta(days=raw_days)
    summary_cutoff = now - timedelta(days=summary_days)
    deleted = {
        "check_results": db.execute(delete(CheckResult).where(CheckResult.checked_at < raw_cutoff)),
        "host_heartbeats": db.execute(
            delete(HostHeartbeat).where(HostHeartbeat.collected_at < raw_cutoff)
        ),
        "container_events": db.execute(
            delete(ContainerEvent).where(ContainerEvent.at < raw_cutoff)
        ),
        "daily_uptime": db.execute(
            delete(DailyUptime).where(DailyUptime.day < summary_cutoff.date())
        ),
        "boot_events": db.execute(delete(BootEvent).where(BootEvent.boot_time < summary_cutoff)),
        # Alerts cascade with their incident. Open incidents are never pruned.
        "incidents": db.execute(
            delete(Incident).where(
                Incident.ended_at.is_not(None), Incident.ended_at < summary_cutoff
            )
        ),
    }
    db.commit()
    return {table: result.rowcount for table, result in deleted.items()}
