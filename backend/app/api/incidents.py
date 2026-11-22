"""Incidents list."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import current_user
from app.db import get_session
from app.models import Incident

router = APIRouter(prefix="/incidents", tags=["incidents"], dependencies=[Depends(current_user)])


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    monitor_id: int | None
    host_id: int | None
    started_at: datetime
    ended_at: datetime | None
    cause: str | None


class IncidentsPage(BaseModel):
    items: list[IncidentOut]
    next_cursor: int | None


@router.get("", response_model=IncidentsPage)
def list_incidents(
    db: DbSession = Depends(get_session),
    status: Literal["open", "closed", "all"] = "all",
    monitor_id: int | None = None,
    cursor: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> IncidentsPage:
    query = select(Incident)
    if status == "open":
        query = query.where(Incident.ended_at.is_(None))
    elif status == "closed":
        query = query.where(Incident.ended_at.is_not(None))
    if monitor_id is not None:
        query = query.where(Incident.monitor_id == monitor_id)
    if cursor is not None:
        query = query.where(Incident.id < cursor)
    rows = list(db.scalars(query.order_by(Incident.id.desc()).limit(limit + 1)))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return IncidentsPage(
        items=[IncidentOut.model_validate(r) for r in rows[:limit]], next_cursor=next_cursor
    )
