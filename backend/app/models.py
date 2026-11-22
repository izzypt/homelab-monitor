"""Database schema (README section 6).

Conventions: bigint identity PKs, timestamptz (UTC), status columns are text + CHECK constraints.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

HOST_STATUSES = ("UNKNOWN", "UP", "STALE")
MONITOR_TYPES = ("http", "dns", "tcp")
MONITOR_STATES = ("PENDING", "UP", "DOWN")
BOOT_KINDS = ("clean", "unexpected", "unknown")
ALERT_KINDS = (
    "down",
    "recovered",
    "unexpected_reboot",
    "tls_expiring",
    "disk_high",
    "network_outage",
)
ALERT_STATUSES = ("pending", "sent", "failed")
INCIDENT_KINDS = ("down", "tls_expiring", "stale", "disk_high", "network_outage")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


def _ts(nullable: bool = False, default_now: bool = False) -> Mapped[Any]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default_now else None,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(default_now=True)
    last_login_at: Mapped[datetime | None] = _ts(nullable=True)


class Host(Base):
    __tablename__ = "hosts"
    __table_args__ = (CheckConstraint(_in("status", HOST_STATUSES), name="status"),)

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    agent_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), server_default="UNKNOWN")
    last_seen_at: Mapped[datetime | None] = _ts(nullable=True)
    current_boot_time: Mapped[datetime | None] = _ts(nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(100))
    agent_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = _ts(default_now=True)


class HostHeartbeat(Base):
    __tablename__ = "host_heartbeats"
    __table_args__ = (Index("ix_host_heartbeats_host_collected", "host_id", "collected_at"),)

    id: Mapped[int] = _pk()
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = _ts()
    received_at: Mapped[datetime] = _ts(default_now=True)
    boot_time: Mapped[datetime] = _ts()
    uptime_s: Mapped[int] = mapped_column(BigInteger)
    load_1m: Mapped[float | None] = mapped_column(Float)
    mem_used_pct: Mapped[float | None] = mapped_column(Float)
    disk_used_pct: Mapped[float | None] = mapped_column(Float)
    daemons: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class BootEvent(Base):
    __tablename__ = "boot_events"
    __table_args__ = (
        CheckConstraint(_in("kind", BOOT_KINDS), name="kind"),
        UniqueConstraint("host_id", "boot_time", name="uq_boot_events_host_boot"),
    )

    id: Mapped[int] = _pk()
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    boot_time: Mapped[datetime] = _ts()
    last_seen_before: Mapped[datetime | None] = _ts(nullable=True)
    shutdown_cause_code: Mapped[int | None] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(String(16), server_default="unknown")
    downtime_s: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _ts(default_now=True)


class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint(_in("type", MONITOR_TYPES), name="type"),
        CheckConstraint(_in("state", MONITOR_STATES), name="state"),
        CheckConstraint("interval_s >= 15", name="interval_min"),
        CheckConstraint("timeout_s > 0 AND timeout_s < interval_s", name="timeout_range"),
        CheckConstraint("failure_threshold >= 1", name="failure_threshold_min"),
        Index("ix_monitors_due", "next_check_at", postgresql_where=text("enabled")),
    )

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(8))
    target: Mapped[str] = mapped_column(String(2048))
    # Type-specific settings, e.g. {"method": "GET", "expected_status": [200], "keyword": "ok"}.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    interval_s: Mapped[int] = mapped_column(Integer, server_default="60")
    timeout_s: Mapped[int] = mapped_column(Integer, server_default="10")
    failure_threshold: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    state: Mapped[str] = mapped_column(String(8), server_default="PENDING")
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_checked_at: Mapped[datetime | None] = _ts(nullable=True)
    next_check_at: Mapped[datetime] = _ts(default_now=True)
    tls_expires_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts(default_now=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        Index("ix_check_results_monitor_checked", "monitor_id", "checked_at"),
        Index("ix_check_results_checked_at", "checked_at"),  # pruning
    )

    id: Mapped[int] = _pk()
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = _ts(default_now=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("num_nonnulls(monitor_id, host_id) = 1", name="one_subject"),
        CheckConstraint(_in("kind", INCIDENT_KINDS), name="kind"),
        Index("ix_incidents_open", "started_at", postgresql_where=text("ended_at IS NULL")),
    )

    id: Mapped[int] = _pk()
    monitor_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), index=True
    )
    host_id: Mapped[int | None] = mapped_column(
        ForeignKey("hosts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), server_default="down")
    started_at: Mapped[datetime] = _ts(default_now=True)
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
    cause: Mapped[str | None] = mapped_column(Text)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(_in("kind", ALERT_KINDS), name="kind"),
        CheckConstraint(_in("status", ALERT_STATUSES), name="status"),
        CheckConstraint("num_nonnulls(incident_id, boot_event_id) = 1", name="one_subject"),
        # One email per subject and kind: retries can never send duplicates.
        UniqueConstraint("incident_id", "kind", name="uq_alerts_incident_kind"),
        UniqueConstraint("boot_event_id", "kind", name="uq_alerts_boot_event_kind"),
    )

    id: Mapped[int] = _pk()
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    boot_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("boot_events.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(default_now=True)
    sent_at: Mapped[datetime | None] = _ts(nullable=True)


class Container(Base):
    __tablename__ = "containers"
    __table_args__ = (UniqueConstraint("host_id", "docker_id", name="uq_containers_host_docker"),)

    id: Mapped[int] = _pk()
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    docker_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    image: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(32))
    health: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = _ts(nullable=True)
    last_seen_at: Mapped[datetime] = _ts(default_now=True)
    removed_at: Mapped[datetime | None] = _ts(nullable=True)


class ContainerEvent(Base):
    __tablename__ = "container_events"
    __table_args__ = (Index("ix_container_events_container_at", "container_id", "at"),)

    id: Mapped[int] = _pk()
    container_id: Mapped[int] = mapped_column(ForeignKey("containers.id", ondelete="CASCADE"))
    at: Mapped[datetime] = _ts(default_now=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))


class DailyUptime(Base):
    __tablename__ = "daily_uptime"
    __table_args__ = (
        CheckConstraint("num_nonnulls(monitor_id, host_id) = 1", name="one_subject"),
        UniqueConstraint("monitor_id", "day", name="uq_daily_uptime_monitor_day"),
        UniqueConstraint("host_id", "day", name="uq_daily_uptime_host_day"),
    )

    id: Mapped[int] = _pk()
    monitor_id: Mapped[int | None] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    uptime_pct: Mapped[float] = mapped_column(Float)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float)
    checks_total: Mapped[int] = mapped_column(Integer)
    checks_failed: Mapped[int] = mapped_column(Integer)
