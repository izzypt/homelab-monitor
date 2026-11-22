"""Monitors CRUD, results, uptime and check-now (README section 7)."""

from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.api.deps import current_user
from app.checks import split_host_port
from app.db import get_session
from app.models import CheckResult, Monitor
from app.monitoring import utcnow

router = APIRouter(prefix="/monitors", tags=["monitors"], dependencies=[Depends(current_user)])

MonitorType = Literal["http", "dns", "tcp"]
DNS_RECORD_TYPES = {"A", "AAAA", "CNAME", "MX", "TXT", "NS"}


def validate_target_and_config(kind: str, target: str, config: dict[str, Any]) -> None:
    if kind == "http":
        parts = urlsplit(target)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("http target must be an http(s) URL")
        if config.get("method", "GET") not in {"GET", "HEAD"}:
            raise ValueError("method must be GET or HEAD")
        expected = config.get("expected_status")
        if expected is not None and (
            not isinstance(expected, list)
            or not all(isinstance(c, int) and 100 <= c <= 599 for c in expected)
        ):
            raise ValueError("expected_status must be a list of HTTP status codes")
    elif kind == "dns":
        if not target or "/" in target or ":" in target:
            raise ValueError("dns target must be a hostname")
        if config.get("record_type", "A") not in DNS_RECORD_TYPES:
            raise ValueError(f"record_type must be one of {sorted(DNS_RECORD_TYPES)}")
    elif kind == "tcp":
        split_host_port(target)


class MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: MonitorType
    target: str = Field(min_length=1, max_length=2048)
    config: dict[str, Any] = Field(default_factory=dict)
    interval_s: int = Field(default=60, ge=15, le=86400)
    timeout_s: int = Field(default=10, ge=1, le=120)
    failure_threshold: int = Field(default=2, ge=1, le=10)
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self):
        validate_target_and_config(self.type, self.target, self.config)
        if self.timeout_s >= self.interval_s:
            raise ValueError("timeout_s must be smaller than interval_s")
        return self


class MonitorCreate(MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    target: str | None = Field(default=None, min_length=1, max_length=2048)
    config: dict[str, Any] | None = None
    interval_s: int | None = Field(default=None, ge=15, le=86400)
    timeout_s: int | None = Field(default=None, ge=1, le=120)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    enabled: bool | None = None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    target: str
    config: dict[str, Any]
    interval_s: int
    timeout_s: int
    failure_threshold: int
    enabled: bool
    state: str
    consecutive_failures: int
    last_checked_at: datetime | None
    next_check_at: datetime
    tls_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CheckResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    checked_at: datetime
    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None


class ResultsPage(BaseModel):
    items: list[CheckResultOut]
    next_cursor: int | None


class UptimeOut(BaseModel):
    days: int
    checks_total: int
    checks_failed: int
    uptime_pct: float | None
    avg_latency_ms: float | None


def _get(db: DbSession, monitor_id: int) -> Monitor:
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monitor not found")
    return monitor


def _commit(db: DbSession) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A monitor with this name exists") from exc


@router.get("", response_model=list[MonitorOut])
def list_monitors(db: DbSession = Depends(get_session)) -> list[Monitor]:
    return list(db.scalars(select(Monitor).order_by(Monitor.name)))


@router.post("", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
def create_monitor(body: MonitorCreate, db: DbSession = Depends(get_session)) -> Monitor:
    monitor = Monitor(**body.model_dump(), next_check_at=utcnow())
    db.add(monitor)
    _commit(db)
    db.refresh(monitor)
    return monitor


@router.get("/{monitor_id}", response_model=MonitorOut)
def get_monitor(monitor_id: int, db: DbSession = Depends(get_session)) -> Monitor:
    return _get(db, monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorOut)
def update_monitor(
    monitor_id: int, body: MonitorUpdate, db: DbSession = Depends(get_session)
) -> Monitor:
    monitor = _get(db, monitor_id)
    changes = body.model_dump(exclude_unset=True)
    merged = MonitorOut.model_validate(monitor).model_dump() | changes
    try:  # validate the resulting monitor as a whole
        MonitorBase.model_validate({k: merged[k] for k in MonitorBase.model_fields})
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    for key, value in changes.items():
        setattr(monitor, key, value)
    if changes.get("enabled") is True:
        monitor.next_check_at = utcnow()
    _commit(db)
    db.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(monitor_id: int, db: DbSession = Depends(get_session)) -> Response:
    db.delete(_get(db, monitor_id))  # cascades to results, incidents and alerts
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/check-now", status_code=status.HTTP_202_ACCEPTED)
def check_now(monitor_id: int, db: DbSession = Depends(get_session)) -> dict[str, str]:
    from app.tasks.monitoring import run_check  # avoid importing Celery at API import time

    monitor = _get(db, monitor_id)
    run_check.apply_async(args=[monitor.id], expires=monitor.interval_s)
    return {"status": "queued"}


@router.get("/{monitor_id}/results", response_model=ResultsPage)
def list_results(
    monitor_id: int,
    db: DbSession = Depends(get_session),
    cursor: int | None = Query(default=None, description="next_cursor from the previous page"),
    limit: int = Query(default=100, ge=1, le=500),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> ResultsPage:
    _get(db, monitor_id)
    query = select(CheckResult).where(CheckResult.monitor_id == monitor_id)
    if cursor is not None:
        query = query.where(CheckResult.id < cursor)
    if from_ is not None:
        query = query.where(CheckResult.checked_at >= from_)
    if to is not None:
        query = query.where(CheckResult.checked_at < to)
    rows = list(db.scalars(query.order_by(CheckResult.id.desc()).limit(limit + 1)))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return ResultsPage(
        items=[CheckResultOut.model_validate(r) for r in rows[:limit]], next_cursor=next_cursor
    )


@router.get("/{monitor_id}/uptime", response_model=UptimeOut)
def uptime(
    monitor_id: int,
    db: DbSession = Depends(get_session),
    days: int = Query(default=30, ge=1, le=30),
) -> UptimeOut:
    _get(db, monitor_id)
    since = utcnow() - timedelta(days=days)
    total, failed, avg_latency = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(cast(~CheckResult.ok, Integer)), 0),
            func.avg(CheckResult.latency_ms),
        ).where(CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= since)
    ).one()
    return UptimeOut(
        days=days,
        checks_total=total,
        checks_failed=failed,
        uptime_pct=round(100 * (total - failed) / total, 3) if total else None,
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency is not None else None,
    )
