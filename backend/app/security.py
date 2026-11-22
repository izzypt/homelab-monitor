"""Password hashing, server-side sessions, CSRF and token helpers (README section 10)."""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache

import redis
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()  # argon2id with library defaults

# A valid hash used to spend the same time on logins for unknown emails (no user enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 for high-entropy random tokens (agent tokens). Not for passwords."""
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url(), decode_responses=True)


@dataclass(frozen=True)
class Session:
    session_id: str
    user_id: int
    csrf_token: str
    created_at: float


class SessionStore:
    """Sessions live in Redis: instantly revocable, sliding idle expiry plus an absolute cap."""

    prefix = "session:"

    def __init__(self, client: redis.Redis | None = None) -> None:
        self.client = client or get_redis()
        self.settings = get_settings()

    def create(self, user_id: int) -> Session:
        session = Session(
            session_id=new_token(32),  # 256 bits
            user_id=user_id,
            csrf_token=new_token(32),
            created_at=time.time(),
        )
        payload = {"user_id": user_id, "csrf": session.csrf_token, "created": session.created_at}
        self.client.set(
            self.prefix + session.session_id, json.dumps(payload), ex=self.settings.session_idle_s
        )
        return session

    def get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        key = self.prefix + session_id
        raw = self.client.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        remaining = self.settings.session_absolute_s - (time.time() - data["created"])
        if remaining <= 0:
            self.client.delete(key)
            return None
        # Slide the idle window, never past the absolute expiry.
        self.client.expire(key, int(min(self.settings.session_idle_s, remaining)))
        return Session(session_id, data["user_id"], data["csrf"], data["created"])

    def delete(self, session_id: str) -> None:
        self.client.delete(self.prefix + session_id)


def csrf_matches(expected: str, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(expected, provided)


def login_rate_limited(client_ip: str, client: redis.Redis | None = None) -> bool:
    """Fixed one-minute window per IP. Returns True when the attempt must be refused."""
    client = client or get_redis()
    key = f"login-attempts:{client_ip}:{int(time.time() // 60)}"
    attempts = client.incr(key)
    if attempts == 1:
        client.expire(key, 61)
    return attempts > get_settings().login_attempts_per_minute
