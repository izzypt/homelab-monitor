"""Containers currently and previously seen on a host, and their state changes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import current_user
from app.db import get_session
from app.models import Container, ContainerEvent

router = APIRouter(prefix="/containers", tags=["containers"], dependencies=[Depends(current_user)])


class ContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host_id: int
    docker_id: str
    name: str
    image: str
    state: str
    health: str | None
    started_at: datetime | None
    last_seen_at: datetime
    removed_at: datetime | None


class ContainerEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    from_state: str | None
    to_state: str


@router.get("", response_model=list[ContainerOut])
def list_containers(
    db: DbSession = Depends(get_session),
    host_id: int | None = None,
    include_removed: bool = False,
) -> list[Container]:
    query = select(Container)
    if host_id is not None:
        query = query.where(Container.host_id == host_id)
    if not include_removed:
        query = query.where(Container.removed_at.is_(None))
    return list(db.scalars(query.order_by(Container.name)))


@router.get("/{container_id}/events", response_model=list[ContainerEventOut])
def list_events(
    container_id: int,
    db: DbSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ContainerEvent]:
    if db.get(Container, container_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Container not found")
    return list(
        db.scalars(
            select(ContainerEvent)
            .where(ContainerEvent.container_id == container_id)
            .order_by(ContainerEvent.at.desc(), ContainerEvent.id.desc())
            .limit(limit)
        )
    )
