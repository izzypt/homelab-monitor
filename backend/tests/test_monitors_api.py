from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CheckResult, Incident, Monitor

URL = "/api/v1/monitors"
BODY = {"name": "website", "type": "http", "target": "https://example.com"}


def test_requires_login(db, redis_client):
    response = TestClient(app).get(URL)
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["status"] == 401


def test_mutations_require_csrf(auth_client):
    response = auth_client.post(URL, json=BODY, headers={"X-XSRF-TOKEN": ""})
    assert response.status_code == 403


def test_create_list_get_update_delete(auth_client, db):
    created = auth_client.post(URL, json=BODY)
    assert created.status_code == 201
    monitor = created.json()
    assert monitor["state"] == "PENDING" and monitor["interval_s"] == 60

    assert [m["name"] for m in auth_client.get(URL).json()] == ["website"]
    assert auth_client.get(f"{URL}/{monitor['id']}").json()["target"] == "https://example.com"

    patched = auth_client.patch(f"{URL}/{monitor['id']}", json={"enabled": False})
    assert patched.status_code == 200 and patched.json()["enabled"] is False

    db.add(CheckResult(monitor_id=monitor["id"], ok=True))
    db.add(Incident(monitor_id=monitor["id"]))
    db.commit()
    assert auth_client.delete(f"{URL}/{monitor['id']}").status_code == 204
    assert auth_client.get(f"{URL}/{monitor['id']}").status_code == 404
    assert db.query(CheckResult).count() == 0  # hard delete cascades
    assert db.query(Incident).count() == 0


def test_duplicate_name_conflicts(auth_client):
    auth_client.post(URL, json=BODY)
    assert auth_client.post(URL, json=BODY).status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "ftp"},
        {"target": "not-a-url"},
        {"interval_s": 5},
        {"timeout_s": 60},
        {"config": {"method": "DELETE"}},
        {"config": {"expected_status": ["200"]}},
        {"type": "dns", "target": "https://example.com"},
        {"type": "dns", "target": "example.com", "config": {"record_type": "SRVX"}},
        {"type": "tcp", "target": "example.com"},
    ],
)
def test_validation(auth_client, overrides):
    response = auth_client.post(URL, json=BODY | overrides)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"


def test_patch_validates_merged_monitor(auth_client):
    monitor = auth_client.post(URL, json=BODY).json()
    response = auth_client.patch(f"{URL}/{monitor['id']}", json={"timeout_s": 90})
    assert response.status_code == 422  # 90 >= interval 60


def test_dns_and_tcp_monitors(auth_client):
    dns = {"name": "dns", "type": "dns", "target": "example.com", "config": {"record_type": "A"}}
    assert auth_client.post(URL, json=dns).status_code == 201
    tcp = {"name": "ssh", "type": "tcp", "target": "192.168.1.10:22"}
    assert auth_client.post(URL, json=tcp).status_code == 201


def test_results_pagination_and_uptime(auth_client, db):
    monitor_id = auth_client.post(URL, json=BODY).json()["id"]
    now = datetime.now(UTC)
    for i in range(5):
        db.add(
            CheckResult(
                monitor_id=monitor_id,
                checked_at=now - timedelta(minutes=i),
                ok=i != 0,
                latency_ms=100,
            )
        )
    db.commit()

    page1 = auth_client.get(f"{URL}/{monitor_id}/results", params={"limit": 3}).json()
    assert len(page1["items"]) == 3 and page1["next_cursor"] is not None
    page2 = auth_client.get(
        f"{URL}/{monitor_id}/results", params={"limit": 3, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["items"]) == 2 and page2["next_cursor"] is None

    uptime = auth_client.get(f"{URL}/{monitor_id}/uptime", params={"days": 1}).json()
    assert uptime == {
        "days": 1,
        "checks_total": 5,
        "checks_failed": 1,
        "uptime_pct": 80.0,
        "avg_latency_ms": 100.0,
    }


def test_check_now_queues_task(auth_client, monkeypatch):
    from app.tasks import monitoring as tasks

    calls = []
    monkeypatch.setattr(tasks.run_check, "apply_async", lambda **kw: calls.append(kw))
    monitor_id = auth_client.post(URL, json=BODY).json()["id"]
    assert auth_client.post(f"{URL}/{monitor_id}/check-now").status_code == 202
    assert calls == [{"args": [monitor_id], "expires": 60}]


def test_incidents_filter(auth_client, db):
    monitor_id = auth_client.post(URL, json=BODY).json()["id"]
    db.add_all(
        [
            Incident(monitor_id=monitor_id),
            Incident(monitor_id=monitor_id, ended_at=datetime.now(UTC)),
        ]
    )
    db.commit()
    assert len(auth_client.get("/api/v1/incidents").json()["items"]) == 2
    open_ = auth_client.get("/api/v1/incidents", params={"status": "open"}).json()["items"]
    assert len(open_) == 1 and open_[0]["ended_at"] is None
    assert db.query(Monitor).count() == 1
