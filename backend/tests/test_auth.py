import json

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api.deps import CSRF_COOKIE, CSRF_HEADER
from app.config import get_settings
from app.main import app
from app.models import User
from app.security import SessionStore, verify_password

EMAIL = "admin@example.com"
PASSWORD = "correct horse battery"


@pytest.fixture
def admin(db, redis_client):
    cli.create_admin(EMAIL, PASSWORD)
    return db.query(User).one()


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_create_admin_hashes_with_argon2_and_resets(db):
    cli.create_admin(EMAIL, PASSWORD)
    user = db.query(User).one()
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, PASSWORD)

    cli.create_admin(EMAIL.upper(), "another long password")
    db.expire_all()
    assert db.query(User).count() == 1
    assert verify_password(db.query(User).one().password_hash, "another long password")


def test_create_admin_rejects_short_password(db):
    with pytest.raises(SystemExit):
        cli.create_admin(EMAIL, "short")


def test_login_sets_cookies_and_me_works(admin, client):
    response = _login(client)
    assert response.status_code == 200
    assert response.json() == {"id": admin.id, "email": EMAIL}

    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith(get_settings().session_cookie_name))
    assert "HttpOnly" in session_cookie
    assert "SameSite=strict" in session_cookie
    csrf_cookie = next(c for c in set_cookie if c.startswith(CSRF_COOKIE))
    assert "HttpOnly" not in csrf_cookie

    assert client.get("/api/v1/auth/me").json()["email"] == EMAIL


@pytest.mark.parametrize(
    ("email", "password"), [(EMAIL, "wrong password"), ("nobody@example.com", PASSWORD)]
)
def test_login_failure_is_generic(admin, client, email, password):
    response = _login(client, email, password)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_me_requires_session(client, redis_client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_is_rate_limited_per_ip(admin, client):
    for _ in range(get_settings().login_attempts_per_minute):
        assert _login(client, password="wrong password").status_code == 401
    assert _login(client).status_code == 429  # even the right password is refused now

    other_ip = TestClient(app, headers={"cf-connecting-ip": "203.0.113.9"})
    assert _login(other_ip).status_code == 200


def test_logout_requires_csrf_then_revokes_session(admin, client):
    _login(client)
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.post("/api/v1/auth/logout", headers={CSRF_HEADER: "not-the-token"}).status_code
        == 403
    )

    token = client.cookies[CSRF_COOKIE]
    assert client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_each_login_gets_a_new_session_id(admin, client):
    _login(client)
    first = client.cookies[get_settings().session_cookie_name]
    _login(client)
    assert client.cookies[get_settings().session_cookie_name] != first


def test_session_absolute_expiry(admin, client, redis_client):
    _login(client)
    sid = client.cookies[get_settings().session_cookie_name]
    key = SessionStore.prefix + sid
    data = json.loads(redis_client.get(key))
    data["created"] -= get_settings().session_absolute_s + 1
    redis_client.set(key, json.dumps(data))

    assert client.get("/api/v1/auth/me").status_code == 401
    assert redis_client.get(key) is None
