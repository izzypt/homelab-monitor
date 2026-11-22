from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import hosts
from app.main import app
from app.models import Alert, BootEvent, Host, HostHeartbeat, Incident
from app.tasks import monitoring as tasks

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
BOOT = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


def _beat(collected=NOW, boot=BOOT, **kw) -> hosts.HeartbeatIn:
    return hosts.HeartbeatIn(
        collected_at=collected,
        boot_time=boot,
        uptime_s=int((collected - boot).total_seconds()),
        **kw,
    )


@pytest.fixture
def host(db) -> Host:
    h = Host(name="mac-mini", agent_token_hash="x" * 64)
    db.add(h)
    db.commit()
    return h


def test_first_heartbeat_sets_boot_without_event(db, host):
    assert hosts.ingest(db, host, [_beat(daemons={"com.simao.colima": True})], NOW) == []
    db.refresh(host)
    assert host.status == "UP" and host.current_boot_time == BOOT and host.last_seen_at == NOW
    assert db.query(BootEvent).count() == 0
    assert db.query(HostHeartbeat).one().daemons == {"com.simao.colima": True}


def test_unexpected_reboot_records_event_and_alert(db, host):
    hosts.ingest(db, host, [_beat()], NOW)
    new_boot = NOW + timedelta(minutes=20)
    later = new_boot + timedelta(minutes=1)
    (alert_id,) = hosts.ingest(db, host, [_beat(later, new_boot, shutdown_cause=0)], later)

    event = db.query(BootEvent).one()
    assert event.kind == "unexpected" and event.shutdown_cause_code == 0
    assert event.last_seen_before == NOW
    assert event.downtime_s == 20 * 60
    assert db.get(Alert, alert_id).kind == "unexpected_reboot"


def test_clean_reboot_records_event_without_alert(db, host):
    hosts.ingest(db, host, [_beat()], NOW)
    new_boot = NOW + timedelta(minutes=5)
    assert hosts.ingest(db, host, [_beat(new_boot, new_boot, shutdown_cause=5)], new_boot) == []
    assert db.query(BootEvent).one().kind == "clean"


def test_small_boot_time_drift_is_not_a_reboot(db, host):
    hosts.ingest(db, host, [_beat()], NOW)
    hosts.ingest(db, host, [_beat(NOW, BOOT + timedelta(seconds=2))], NOW)
    assert db.query(BootEvent).count() == 0


@pytest.mark.parametrize(
    ("code", "kind"), [(5, "clean"), (0, "unexpected"), (-128, "unexpected"), (None, "unknown")]
)
def test_classify_shutdown(code, kind):
    assert hosts.classify_shutdown(code) == kind


def test_buffered_backlog_uses_collected_at_but_receive_time_for_liveness(db, host):
    backlog = [_beat(NOW - timedelta(minutes=m)) for m in (20, 10, 0)]
    hosts.ingest(db, host, list(reversed(backlog)), NOW + timedelta(seconds=5))
    db.refresh(host)
    assert host.last_seen_at == NOW + timedelta(seconds=5)
    collected = sorted(hb.collected_at for hb in db.query(HostHeartbeat))
    assert collected == [b.collected_at for b in backlog]


def test_stale_then_recovered(db, host):
    hosts.ingest(db, host, [_beat()], NOW)
    assert hosts.mark_stale_hosts(db, NOW + timedelta(seconds=60)) == []  # within 90 s
    (down,) = hosts.mark_stale_hosts(db, NOW + timedelta(seconds=120))
    db.refresh(host)
    assert host.status == "STALE"
    assert db.get(Alert, down).kind == "down"
    assert hosts.mark_stale_hosts(db, NOW + timedelta(seconds=300)) == []  # one alert only

    (recovered,) = hosts.ingest(
        db, host, [_beat(NOW + timedelta(minutes=6))], NOW + timedelta(minutes=6)
    )
    db.refresh(host)
    assert host.status == "UP"
    assert db.get(Alert, recovered).kind == "recovered"
    assert db.query(Incident).one().ended_at is not None


def test_disk_alert_with_hysteresis(db, host):
    (alert_id,) = hosts.ingest(db, host, [_beat(disk_used_pct=93.0)], NOW)
    assert db.get(Alert, alert_id).kind == "disk_high"
    assert hosts.ingest(db, host, [_beat(disk_used_pct=94.0)], NOW) == []  # already open
    hosts.ingest(db, host, [_beat(disk_used_pct=88.0)], NOW)  # between 85 and 90: stays open
    assert db.query(Incident).one().ended_at is None
    hosts.ingest(db, host, [_beat(disk_used_pct=80.0)], NOW)
    assert db.query(Incident).one().ended_at is not None


def test_evaluate_hosts_task_queues_alerts(db, host, monkeypatch):
    hosts.ingest(db, host, [_beat()], NOW)
    queued = []
    monkeypatch.setattr(tasks.send_alert, "delay", lambda alert_id: queued.append(alert_id))
    monkeypatch.setattr(tasks.monitoring, "utcnow", lambda: NOW + timedelta(minutes=5))
    assert tasks.evaluate_hosts() == 1 and len(queued) == 1


# ---------------------------------------------------------------- API


def _payload(**kw):
    return {
        "collected_at": NOW.isoformat(),
        "boot_time": BOOT.isoformat(),
        "uptime_s": 100,
        "disk_used_pct": 40.0,
        "daemons": {"com.simao.colima": True, "com.cloudflare": True},
        "agent_version": "0.1.0",
        "os_version": "macOS 27.2",
    } | kw


def test_create_host_returns_token_once_and_agent_can_post(auth_client, db):
    created = auth_client.post("/api/v1/hosts", json={"name": "mac-mini"})
    assert created.status_code == 201
    token = created.json()["agent_token"]
    assert "agent_token" not in auth_client.get("/api/v1/hosts").json()[0]

    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    response = agent.post("/api/v1/agent/heartbeat", json={"heartbeats": [_payload()]})
    assert response.status_code == 202 and response.json() == {"accepted": 1}

    host_id = created.json()["id"]
    host = auth_client.get(f"/api/v1/hosts/{host_id}").json()
    assert host["status"] == "UP" and host["os_version"] == "macOS 27.2"
    beats = auth_client.get(f"/api/v1/hosts/{host_id}/heartbeats").json()["items"]
    assert beats[0]["daemons"]["com.cloudflare"] is True
    assert auth_client.get(f"/api/v1/hosts/{host_id}/boots").json() == []


def test_agent_auth_and_validation(auth_client):
    token = auth_client.post("/api/v1/hosts", json={"name": "mac-mini"}).json()["agent_token"]
    url = "/api/v1/agent/heartbeat"
    body = {"heartbeats": [_payload()]}

    assert TestClient(app).post(url, json=body).status_code == 401
    bad = TestClient(app, headers={"Authorization": "Bearer nope"})
    assert bad.post(url, json=body).status_code == 401

    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert agent.post(url, json={"heartbeats": []}).status_code == 422
    assert agent.post(url, json={"heartbeats": [_payload(disk_used_pct=150)]}).status_code == 422
    naive = _payload(collected_at="2026-11-22T12:00:00")
    assert agent.post(url, json={"heartbeats": [naive]}).status_code == 422
    too_many = {"heartbeats": [_payload()] * 201}
    assert agent.post(url, json=too_many).status_code == 422


def test_rotate_token_invalidates_old(auth_client):
    created = auth_client.post("/api/v1/hosts", json={"name": "mac-mini"}).json()
    rotated = auth_client.post(f"/api/v1/hosts/{created['id']}/rotate-token").json()
    url = "/api/v1/agent/heartbeat"
    body = {"heartbeats": [_payload()]}
    old = TestClient(app, headers={"Authorization": f"Bearer {created['agent_token']}"})
    new = TestClient(app, headers={"Authorization": f"Bearer {rotated['agent_token']}"})
    assert old.post(url, json=body).status_code == 401
    assert new.post(url, json=body).status_code == 202


def test_host_endpoints_require_login(db, redis_client):
    assert TestClient(app).get("/api/v1/hosts").status_code == 401


def test_duplicate_host_name(auth_client):
    auth_client.post("/api/v1/hosts", json={"name": "mac-mini"})
    assert auth_client.post("/api/v1/hosts", json={"name": "mac-mini"}).status_code == 409
    assert auth_client.post("/api/v1/hosts", json={"name": "bad name!"}).status_code == 422
