"""Container snapshots through the read-only Docker socket proxy (README section 5.4).

Only changes are stored: a current-state row per container plus one event per transition.
Container changes are shown in the UI but never emailed (Simão's decision).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Container, ContainerEvent, Host

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContainerInfo:
    docker_id: str
    name: str
    image: str
    state: str  # running, exited, restarting, paused, created, dead
    health: str | None  # healthy, unhealthy, starting, or None without a healthcheck
    started_at: datetime | None


def _health(status: str) -> str | None:
    # Docker puts health in the human-readable Status, e.g. "Up 2 hours (healthy)".
    for value in ("unhealthy", "healthy", "health: starting"):
        if f"({value})" in status:
            return "starting" if value == "health: starting" else value
    return None


def parse_containers(payload: list[dict]) -> list[ContainerInfo]:
    """Parse `GET /containers/json?all=1` from the Docker Engine API."""
    infos = []
    for item in payload:
        names = item.get("Names") or [item["Id"][:12]]
        created = item.get("Created")
        infos.append(
            ContainerInfo(
                docker_id=item["Id"],
                name=names[0].lstrip("/"),
                image=item.get("Image", ""),
                state=item.get("State", "unknown"),
                health=_health(item.get("Status", "")),
                # The list endpoint has no StartedAt; Created is the closest stable value.
                started_at=datetime.fromtimestamp(created, UTC) if created else None,
            )
        )
    return infos


def fetch_containers(base_url: str, transport: httpx.BaseTransport | None = None) -> list[dict]:
    with httpx.Client(base_url=base_url, timeout=10, transport=transport) as client:
        response = client.get("/containers/json", params={"all": 1})
        response.raise_for_status()
        return response.json()


def _status(state: str, health: str | None) -> str:
    return f"{state} ({health})" if health else state


def apply_snapshot(db: Session, host: Host, infos: list[ContainerInfo], now: datetime) -> int:
    """Upsert containers, record state changes, mark vanished ones removed. Returns #events."""
    existing = {
        c.docker_id: c
        for c in db.scalars(select(Container).where(Container.host_id == host.id).with_for_update())
    }
    events = 0
    seen: set[str] = set()
    for info in infos:
        seen.add(info.docker_id)
        row = existing.get(info.docker_id)
        if row is None:
            row = Container(
                host_id=host.id,
                docker_id=info.docker_id,
                name=info.name,
                image=info.image,
                state=info.state,
                health=info.health,
                started_at=info.started_at,
                last_seen_at=now,
            )
            db.add(row)
            db.flush()
            db.add(
                ContainerEvent(
                    container_id=row.id,
                    at=now,
                    from_state=None,
                    to_state=_status(info.state, info.health),
                )
            )
            events += 1
            continue
        before, after = _status(row.state, row.health), _status(info.state, info.health)
        if before != after or row.removed_at is not None:
            db.add(ContainerEvent(container_id=row.id, at=now, from_state=before, to_state=after))
            events += 1
        row.name, row.image, row.state, row.health = info.name, info.image, info.state, info.health
        row.started_at, row.last_seen_at, row.removed_at = info.started_at, now, None

    for docker_id, row in existing.items():
        if docker_id not in seen and row.removed_at is None:
            row.removed_at = now
            db.add(
                ContainerEvent(
                    container_id=row.id,
                    at=now,
                    from_state=_status(row.state, row.health),
                    to_state="removed",
                )
            )
            events += 1
    db.commit()
    return events
