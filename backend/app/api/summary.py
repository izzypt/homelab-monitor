"""Dashboard summary: everything the overview page needs in one request (README section 7)."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import current_user
from app.api.hosts import BootEventOut
from app.db import get_session
from app.models import BootEvent, Container, Host, HostHeartbeat, Incident, Monitor
from app.monitoring import NETWORK_OUTAGE_KEY, utcnow
from app.security import get_redis

router = APIRouter(prefix="/summary", tags=["summary"], dependencies=[Depends(current_user)])


class LatestHeartbeat(BaseModel):
    collected_at: datetime
    load_1m: float | None
    mem_used_pct: float | None
    disk_used_pct: float | None
    daemons: dict[str, Any]


class HostSummary(BaseModel):
    id: int
    name: str
    status: str
    last_seen_at: datetime | None
    current_boot_time: datetime | None
    uptime_s: int | None
    os_version: str | None
    latest: LatestHeartbeat | None
    last_boot: BootEventOut | None


class MonitorCounts(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    up: int = 0
    down: int = 0
    pending: int = 0
    paused: int = 0


class ContainerCounts(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    running: int = 0
    unhealthy: int = 0


class Summary(BaseModel):
    generated_at: datetime
    network_outage: bool
    open_incidents: int
    hosts: list[HostSummary]
    monitors: MonitorCounts
    containers: ContainerCounts


def _host_summary(db: DbSession, host: Host, now: datetime) -> HostSummary:
    latest = db.scalar(
        select(HostHeartbeat)
        .where(HostHeartbeat.host_id == host.id)
        .order_by(HostHeartbeat.collected_at.desc())
        .limit(1)
    )
    last_boot = db.scalar(
        select(BootEvent)
        .where(BootEvent.host_id == host.id)
        .order_by(BootEvent.boot_time.desc())
        .limit(1)
    )
    uptime = None
    if host.current_boot_time is not None and host.status == "UP":
        uptime = max(0, int((now - host.current_boot_time).total_seconds()))
    return HostSummary(
        id=host.id,
        name=host.name,
        status=host.status,
        last_seen_at=host.last_seen_at,
        current_boot_time=host.current_boot_time,
        uptime_s=uptime,
        os_version=host.os_version,
        latest=LatestHeartbeat.model_validate(latest, from_attributes=True) if latest else None,
        last_boot=BootEventOut.model_validate(last_boot) if last_boot else None,
    )


@router.get("", response_model=Summary)
def get_summary(db: DbSession = Depends(get_session)) -> Summary:
    now = utcnow()
    monitors = MonitorCounts()
    for enabled, state, count in db.execute(
        select(Monitor.enabled, Monitor.state, func.count()).group_by(
            Monitor.enabled, Monitor.state
        )
    ):
        monitors.total += count
        if not enabled:
            monitors.paused += count
        else:
            key = state.lower()
            setattr(monitors, key, getattr(monitors, key) + count)

    containers = ContainerCounts()
    for state, health in db.execute(
        select(Container.state, Container.health).where(Container.removed_at.is_(None))
    ):
        containers.total += 1
        containers.running += state == "running"
        containers.unhealthy += health == "unhealthy"

    return Summary(
        generated_at=now,
        network_outage=bool(get_redis().exists(NETWORK_OUTAGE_KEY)),
        open_incidents=db.scalar(
            select(func.count()).select_from(Incident).where(Incident.ended_at.is_(None))
        )
        or 0,
        hosts=[_host_summary(db, h, now) for h in db.scalars(select(Host).order_by(Host.name))],
        monitors=monitors,
        containers=containers,
    )
