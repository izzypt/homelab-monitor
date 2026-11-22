"""Hosts (admin) and the agent heartbeat endpoint (README section 7)."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import hosts as host_logic
from app.api.deps import current_user
from app.db import get_session
from app.models import BootEvent, Host, HostHeartbeat
from app.monitoring import utcnow
from app.security import hash_token, new_token

router = APIRouter(prefix="/hosts", tags=["hosts"], dependencies=[Depends(current_user)])
agent_router = APIRouter(prefix="/agent", tags=["agent"])

MAX_BATCH = 200  # ~1h40 of buffered heartbeats; the agent caps its spool below this


class HostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class HostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    last_seen_at: datetime | None
    current_boot_time: datetime | None
    os_version: str | None
    agent_version: str | None
    created_at: datetime


class HostWithToken(HostOut):
    agent_token: str = Field(description="Shown once. Store it in the agent config.")


class HeartbeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    collected_at: datetime
    received_at: datetime
    boot_time: datetime
    uptime_s: int
    load_1m: float | None
    mem_used_pct: float | None
    disk_used_pct: float | None
    daemons: dict[str, Any]


class HeartbeatsPage(BaseModel):
    items: list[HeartbeatOut]
    next_cursor: int | None


class BootEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    boot_time: datetime
    last_seen_before: datetime | None
    shutdown_cause_code: int | None
    kind: str
    downtime_s: int | None


class HeartbeatPayload(BaseModel):
    collected_at: datetime
    boot_time: datetime
    uptime_s: int = Field(ge=0)
    load_1m: float | None = Field(default=None, ge=0)
    mem_used_pct: float | None = Field(default=None, ge=0, le=100)
    disk_used_pct: float | None = Field(default=None, ge=0, le=100)
    daemons: dict[str, bool] = Field(default_factory=dict, max_length=20)
    os_version: str | None = Field(default=None, max_length=100)
    agent_version: str | None = Field(default=None, max_length=50)
    shutdown_cause: int | None = Field(default=None, ge=-32768, le=32767)

    @model_validator(mode="after")
    def _aware(self):
        if self.collected_at.tzinfo is None or self.boot_time.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return self


class HeartbeatBatch(BaseModel):
    heartbeats: list[HeartbeatPayload] = Field(min_length=1, max_length=MAX_BATCH)


def _get(db: DbSession, host_id: int) -> Host:
    host = db.get(Host, host_id)
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Host not found")
    return host


@router.get("", response_model=list[HostOut])
def list_hosts(db: DbSession = Depends(get_session)) -> list[Host]:
    return list(db.scalars(select(Host).order_by(Host.name)))


@router.post("", response_model=HostWithToken, status_code=status.HTTP_201_CREATED)
def create_host(body: HostCreate, db: DbSession = Depends(get_session)) -> HostWithToken:
    token = new_token(32)
    host = Host(name=body.name, agent_token_hash=hash_token(token))
    db.add(host)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A host with this name exists") from exc
    db.refresh(host)
    return HostWithToken(**HostOut.model_validate(host).model_dump(), agent_token=token)


@router.get("/{host_id}", response_model=HostOut)
def get_host(host_id: int, db: DbSession = Depends(get_session)) -> Host:
    return _get(db, host_id)


@router.post("/{host_id}/rotate-token", response_model=HostWithToken)
def rotate_token(host_id: int, db: DbSession = Depends(get_session)) -> HostWithToken:
    host = _get(db, host_id)
    token = new_token(32)
    host.agent_token_hash = hash_token(token)
    db.commit()
    db.refresh(host)
    return HostWithToken(**HostOut.model_validate(host).model_dump(), agent_token=token)


@router.get("/{host_id}/heartbeats", response_model=HeartbeatsPage)
def list_heartbeats(
    host_id: int,
    db: DbSession = Depends(get_session),
    cursor: int | None = None,
    limit: int = Query(default=120, ge=1, le=1000),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> HeartbeatsPage:
    _get(db, host_id)
    query = select(HostHeartbeat).where(HostHeartbeat.host_id == host_id)
    if cursor is not None:
        query = query.where(HostHeartbeat.id < cursor)
    if from_ is not None:
        query = query.where(HostHeartbeat.collected_at >= from_)
    if to is not None:
        query = query.where(HostHeartbeat.collected_at < to)
    rows = list(db.scalars(query.order_by(HostHeartbeat.id.desc()).limit(limit + 1)))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return HeartbeatsPage(
        items=[HeartbeatOut.model_validate(r) for r in rows[:limit]], next_cursor=next_cursor
    )


@router.get("/{host_id}/boots", response_model=list[BootEventOut])
def list_boots(
    host_id: int, db: DbSession = Depends(get_session), limit: int = Query(default=50, le=200)
) -> list[BootEvent]:
    _get(db, host_id)
    return list(
        db.scalars(
            select(BootEvent)
            .where(BootEvent.host_id == host_id)
            .order_by(BootEvent.boot_time.desc())
            .limit(limit)
        )
    )


def agent_host(
    authorization: str | None = Header(default=None), db: DbSession = Depends(get_session)
) -> Host:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing bearer token", {"WWW-Authenticate": "Bearer"}
        )
    host = db.scalar(select(Host).where(Host.agent_token_hash == hash_token(token)))
    if host is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid agent token", {"WWW-Authenticate": "Bearer"}
        )
    return host


@agent_router.post("/heartbeat", status_code=status.HTTP_202_ACCEPTED)
def heartbeat(
    body: HeartbeatBatch,
    host: Host = Depends(agent_host),
    db: DbSession = Depends(get_session),
) -> dict[str, int]:
    """Accepts one or more heartbeats (the agent flushes its local spool as a batch)."""
    beats = [host_logic.HeartbeatIn(**hb.model_dump()) for hb in body.heartbeats]
    alert_ids = host_logic.ingest(db, host, beats, utcnow())
    if alert_ids:
        from app.tasks.monitoring import send_alert

        for alert_id in alert_ids:
            send_alert.delay(alert_id)
    return {"accepted": len(beats)}
