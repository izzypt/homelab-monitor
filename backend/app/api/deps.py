"""Shared API dependencies: database session, current user, CSRF."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.db import get_session
from app.models import User
from app.security import Session, SessionStore, csrf_matches

CSRF_COOKIE = "XSRF-TOKEN"  # Angular HttpClient reads this cookie...
CSRF_HEADER = "X-XSRF-TOKEN"  # ...and echoes it in this header on mutating requests.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_session_store() -> SessionStore:
    return SessionStore()


def client_ip(request: Request) -> str:
    # Traffic only reaches the API through Cloudflare -> tunnel -> nginx, so this header is set
    # by Cloudflare. Falls back to the socket peer for local development.
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def current_session(request: Request, store: SessionStore = Depends(get_session_store)) -> Session:
    session = store.get(request.cookies.get(get_settings().session_cookie_name))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if request.method not in SAFE_METHODS and not csrf_matches(
        session.csrf_token, request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    return session


def current_user(
    session: Session = Depends(current_session), db: DbSession = Depends(get_session)
) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
