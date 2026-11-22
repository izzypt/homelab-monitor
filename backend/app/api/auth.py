"""Login, logout and current user."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import CSRF_COOKIE, client_ip, current_session, current_user, get_session_store
from app.config import get_settings
from app.db import get_session
from app.models import User
from app.security import Session, SessionStore, login_rate_limited, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    id: int
    email: str


def _set_session_cookies(response: Response, session: Session) -> None:
    settings = get_settings()
    common = {"secure": settings.session_cookie_secure, "samesite": "strict", "path": "/"}
    response.set_cookie(
        settings.session_cookie_name,
        session.session_id,
        max_age=settings.session_absolute_s,
        httponly=True,
        **common,
    )
    # Readable by the SPA (not HttpOnly) so Angular can send it back as X-XSRF-TOKEN.
    response.set_cookie(
        CSRF_COOKIE, session.csrf_token, max_age=settings.session_absolute_s, **common
    )


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_session),
    store: SessionStore = Depends(get_session_store),
) -> UserOut:
    ip = client_ip(request)
    if login_rate_limited(ip, store.client):
        log.warning("login rate limited ip=%s", ip)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts")

    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        log.warning("login failed ip=%s", ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # A fresh session ID on every login (no session fixation). Old sessions are left to expire.
    session = store.create(user.id)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    _set_session_cookies(response, session)
    log.info("login ok user_id=%s ip=%s", user.id, ip)
    return UserOut(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: Session = Depends(current_session),
    store: SessionStore = Depends(get_session_store),
) -> None:
    store.delete(session.session_id)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)
