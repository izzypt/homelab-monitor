from fastapi.testclient import TestClient

from app.api.health import get_dependency_checks
from app.main import app

client = TestClient(app)


def _ok() -> None:
    return None


def _fail() -> None:
    raise ConnectionError("unreachable")


def test_healthz_is_ok_without_dependencies():
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_all_dependencies_respond():
    app.dependency_overrides[get_dependency_checks] = lambda: {"postgres": _ok, "redis": _ok}
    try:
        response = client.get("/api/readyz")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


def test_readyz_503_when_a_dependency_fails():
    app.dependency_overrides[get_dependency_checks] = lambda: {"postgres": _ok, "redis": _fail}
    try:
        response = client.get("/api/readyz")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["checks"] == {"postgres": "ok", "redis": "error"}
