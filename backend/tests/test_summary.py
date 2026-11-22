from datetime import UTC, datetime, timedelta

from app import containers, monitoring
from app.models import BootEvent, Host, HostHeartbeat, Incident, Monitor

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
BOOT = NOW - timedelta(days=2)


def test_summary_requires_login(db):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/v1/summary").status_code == 401


def test_summary_empty(auth_client):
    body = auth_client.get("/api/v1/summary").json()
    assert body["hosts"] == [] and body["open_incidents"] == 0
    assert body["monitors"] == {"total": 0, "up": 0, "down": 0, "pending": 0, "paused": 0}
    assert body["network_outage"] is False


def test_summary_counts(auth_client, db, redis_client, monkeypatch):
    monkeypatch.setattr(monitoring, "utcnow", lambda: NOW)
    monkeypatch.setattr("app.api.summary.utcnow", lambda: NOW)
    host = Host(
        name="mac-mini",
        agent_token_hash="x" * 64,
        status="UP",
        current_boot_time=BOOT,
        last_seen_at=NOW,
    )
    db.add(host)
    db.flush()
    db.add_all(
        [
            Monitor(name="a", type="http", target="https://a.test", state="UP"),
            Monitor(name="b", type="http", target="https://b.test", state="DOWN"),
            Monitor(name="c", type="http", target="https://c.test", state="UP", enabled=False),
            Monitor(name="d", type="tcp", target="nas:22"),
            HostHeartbeat(
                host_id=host.id,
                collected_at=NOW,
                boot_time=BOOT,
                uptime_s=172800,
                disk_used_pct=42.5,
                daemons={"com.simao.colima": True},
            ),
            BootEvent(host_id=host.id, boot_time=BOOT, kind="unexpected", downtime_s=60),
            Incident(host_id=host.id, kind="stale", started_at=NOW),
        ]
    )
    db.commit()
    api = containers.ContainerInfo("a" * 64, "api", "api:1", "running", "unhealthy", NOW)
    old = containers.ContainerInfo("b" * 64, "old", "x:1", "exited", None, NOW)
    containers.apply_snapshot(db, host, [api, old], NOW)
    redis_client.set(monitoring.NETWORK_OUTAGE_KEY, "1")

    body = auth_client.get("/api/v1/summary").json()
    assert body["monitors"] == {"total": 4, "up": 1, "down": 1, "pending": 1, "paused": 1}
    assert body["containers"] == {"total": 2, "running": 1, "unhealthy": 1}
    assert body["open_incidents"] == 1 and body["network_outage"] is True
    [h] = body["hosts"]
    assert h["uptime_s"] == 172800 and h["latest"]["disk_used_pct"] == 42.5
    assert h["last_boot"]["kind"] == "unexpected"
