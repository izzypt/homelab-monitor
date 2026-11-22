from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app import containers, maintenance, monitoring
from app.checks import CheckOutcome
from app.models import (
    Alert,
    CheckResult,
    Container,
    ContainerEvent,
    DailyUptime,
    Host,
    HostHeartbeat,
    Incident,
    Monitor,
)
from app.tasks import monitoring as tasks

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def host(db) -> Host:
    h = Host(name="mac-mini", agent_token_hash="x" * 64)
    db.add(h)
    db.commit()
    return h


def _docker(id_, name, state="running", status="Up 2 hours", created=1763800000):
    return {
        "Id": id_,
        "Names": [f"/{name}"],
        "Image": f"{name}:latest",
        "State": state,
        "Status": status,
        "Created": created,
    }


# ---------------------------------------------------------------- containers


def test_parse_containers_health():
    infos = containers.parse_containers(
        [
            _docker("a" * 64, "api", status="Up 1 hour (healthy)"),
            _docker("b" * 64, "db", status="Up 5 seconds (health: starting)"),
            _docker("c" * 64, "old", state="exited", status="Exited (0) 2 days ago"),
        ]
    )
    assert [(i.name, i.state, i.health) for i in infos] == [
        ("api", "running", "healthy"),
        ("db", "running", "starting"),
        ("old", "exited", None),
    ]


def test_fetch_containers_uses_read_only_endpoint():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[_docker("a" * 64, "api")])

    payload = containers.fetch_containers("http://proxy:2375", httpx.MockTransport(handler))
    assert len(payload) == 1
    assert seen == [("GET", "/containers/json", {"all": "1"})]


def test_snapshot_records_only_changes(db, host):
    api = containers.ContainerInfo("a" * 64, "api", "api:1", "running", "healthy", NOW)
    db_ = containers.ContainerInfo("b" * 64, "db", "pg:16", "running", None, NOW)

    assert containers.apply_snapshot(db, host, [api, db_], NOW) == 2  # first sight
    assert containers.apply_snapshot(db, host, [api, db_], NOW + timedelta(minutes=1)) == 0

    unhealthy = containers.ContainerInfo("a" * 64, "api", "api:1", "running", "unhealthy", NOW)
    assert containers.apply_snapshot(db, host, [unhealthy, db_], NOW + timedelta(minutes=2)) == 1
    assert containers.apply_snapshot(db, host, [unhealthy], NOW + timedelta(minutes=3)) == 1

    removed = db.query(Container).filter_by(name="db").one()
    assert removed.removed_at == NOW + timedelta(minutes=3)
    events = [
        (e.from_state, e.to_state) for e in db.query(ContainerEvent).order_by(ContainerEvent.id)
    ]
    assert events == [
        (None, "running (healthy)"),
        (None, "running"),
        ("running (healthy)", "running (unhealthy)"),
        ("running", "removed"),
    ]
    assert db.query(Alert).count() == 0  # container changes are never emailed


def test_snapshot_task_without_host_or_docker(db, monkeypatch):
    def boom(url):
        raise httpx.ConnectError("no proxy")

    monkeypatch.setattr(tasks.containers, "fetch_containers", boom)
    assert tasks.snapshot_containers() == 0
    monkeypatch.setattr(tasks.containers, "fetch_containers", lambda url: [])
    assert tasks.snapshot_containers() == 0  # no host named mac-mini yet


def test_containers_api(auth_client, db, host):
    api = containers.ContainerInfo("a" * 64, "api", "api:1", "running", None, NOW)
    gone = containers.ContainerInfo("b" * 64, "gone", "x:1", "exited", None, NOW)
    containers.apply_snapshot(db, host, [api, gone], NOW)
    containers.apply_snapshot(db, host, [api], NOW + timedelta(minutes=1))

    current = auth_client.get("/api/v1/containers").json()
    assert [c["name"] for c in current] == ["api"]
    everything = auth_client.get("/api/v1/containers", params={"include_removed": True}).json()
    assert {c["name"] for c in everything} == {"api", "gone"}
    gone_id = next(c["id"] for c in everything if c["name"] == "gone")
    events = auth_client.get(f"/api/v1/containers/{gone_id}/events").json()
    assert [e["to_state"] for e in events] == ["removed", "exited"]
    assert auth_client.get("/api/v1/containers/999/events").status_code == 404


# ---------------------------------------------------------------- network outage

FAIL = CheckOutcome(ok=False, error="timeout")
OK = CheckOutcome(ok=True, latency_ms=5, status_code=200)


def test_suppressed_down_has_no_alerts_and_no_recovery_email(db):
    m = Monitor(name="site", type="http", target="https://x.test", failure_threshold=1)
    db.add(m)
    db.commit()
    assert monitoring.record_result(db, m.id, FAIL, NOW, suppress_alerts=True) == []
    assert db.query(Incident).one().kind == "down"
    assert monitoring.record_result(db, m.id, OK, NOW + timedelta(minutes=1)) == []
    assert db.query(Alert).count() == 0


def test_check_network_opens_one_outage_and_recovers(db, redis_client, host, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.send_alert, "delay", lambda alert_id: queued.append(alert_id))
    monkeypatch.setattr(tasks.checks, "check_http", lambda url, cfg, timeout: FAIL)

    assert tasks.check_network() == "down"  # 1st failure: not yet
    assert not redis_client.exists(tasks.NETWORK_OUTAGE_KEY)
    assert tasks.check_network() == "down"
    assert redis_client.exists(tasks.NETWORK_OUTAGE_KEY)
    assert tasks.check_network() == "down"
    incident = db.query(Incident).one()
    assert incident.kind == "network_outage" and incident.host_id == host.id
    assert [db.get(Alert, a).kind for a in queued] == ["network_outage"]

    monkeypatch.setattr(tasks.checks, "check_http", lambda url, cfg, timeout: OK)
    assert tasks.check_network() == "ok"
    assert not redis_client.exists(tasks.NETWORK_OUTAGE_KEY)
    db.expire_all()
    assert db.query(Incident).one().ended_at is not None
    assert [db.get(Alert, a).kind for a in queued] == ["network_outage", "recovered"]


def test_run_check_suppresses_during_outage(db, redis_client, monkeypatch):
    m = Monitor(name="site", type="http", target="https://x.test", failure_threshold=1)
    db.add(m)
    db.commit()
    redis_client.set(tasks.NETWORK_OUTAGE_KEY, "1")
    monkeypatch.setattr(tasks.checks, "run", lambda *a: FAIL)
    queued = []
    monkeypatch.setattr(tasks.send_alert, "delay", lambda alert_id: queued.append(alert_id))
    tasks.run_check(m.id)
    assert queued == []
    db.refresh(m)
    assert m.state == "DOWN"


# ---------------------------------------------------------------- rollup and prune


def test_rollup_day_monitors_and_hosts(db, host):
    m = Monitor(name="site", type="http", target="https://x.test")
    db.add(m)
    db.commit()
    day = date(2026, 11, 21)
    start, _ = maintenance.day_bounds(day, "Europe/Lisbon")
    for i in range(4):
        db.add(
            CheckResult(
                monitor_id=m.id, checked_at=start + timedelta(hours=i), ok=i != 3, latency_ms=100
            )
        )
    for i in range(1440):  # half a day of 30 s heartbeats
        t = start + timedelta(seconds=30 * i)
        db.add(HostHeartbeat(host_id=host.id, collected_at=t, boot_time=start, uptime_s=0))
    db.commit()

    assert maintenance.rollup_day(db, day, "Europe/Lisbon") == 2
    assert maintenance.rollup_day(db, day, "Europe/Lisbon") == 2  # idempotent upsert
    rows = {(r.monitor_id, r.host_id): r for r in db.query(DailyUptime)}
    assert len(rows) == 2
    monitor_row, host_row = rows[(m.id, None)], rows[(None, host.id)]
    assert (monitor_row.uptime_pct, monitor_row.checks_total, monitor_row.checks_failed) == (
        75.0,
        4,
        1,
    )
    assert host_row.uptime_pct == 50.0


def test_day_bounds_handles_dst():
    start, end = maintenance.day_bounds(date(2026, 10, 25), "Europe/Lisbon")  # 25 h day
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=25)


def test_prune_respects_retention(db, host):
    m = Monitor(name="site", type="http", target="https://x.test")
    db.add(m)
    db.commit()
    old, recent = NOW - timedelta(days=40), NOW - timedelta(days=1)
    db.add_all(
        [
            CheckResult(monitor_id=m.id, checked_at=old, ok=True),
            CheckResult(monitor_id=m.id, checked_at=recent, ok=True),
            HostHeartbeat(host_id=host.id, collected_at=old, boot_time=old, uptime_s=0),
            DailyUptime(
                monitor_id=m.id,
                day=(NOW - timedelta(days=200)).date(),
                uptime_pct=100,
                checks_total=1,
                checks_failed=0,
            ),
            Incident(monitor_id=m.id, started_at=old, ended_at=NOW - timedelta(days=200)),
            Incident(monitor_id=m.id, started_at=NOW - timedelta(days=300)),  # still open: kept
        ]
    )
    db.commit()
    deleted = maintenance.prune(db, NOW, raw_days=30, summary_days=183)
    assert deleted["check_results"] == 1
    assert deleted["host_heartbeats"] == 1
    assert deleted["daily_uptime"] == 1
    assert deleted["incidents"] == 1
    assert db.query(Incident).one().ended_at is None


def test_rollup_and_prune_task(db, monkeypatch):
    monkeypatch.setattr(tasks.monitoring, "utcnow", lambda: NOW)
    result = tasks.rollup_and_prune()
    assert result["rollup_rows"] == 0 and result["check_results"] == 0
