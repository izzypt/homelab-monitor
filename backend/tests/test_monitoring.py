from datetime import UTC, datetime, timedelta

import pytest

from app import alerts, monitoring
from app.checks import CheckOutcome
from app.models import Alert, CheckResult, Incident, Monitor
from app.tasks import monitoring as tasks

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
OK = CheckOutcome(ok=True, latency_ms=42, status_code=200)
FAIL = CheckOutcome(ok=False, latency_ms=10, error="unexpected status 503", status_code=503)


def _monitor(db, **kw) -> Monitor:
    m = Monitor(
        name=kw.pop("name", "site"),
        type="http",
        target="https://example.com",
        next_check_at=kw.pop("next_check_at", NOW),
        **kw,
    )
    db.add(m)
    db.commit()
    return m


def test_claim_due_monitors_only_claims_due_enabled(db):
    due = _monitor(db, name="due")
    _monitor(db, name="later", next_check_at=NOW + timedelta(seconds=30))
    _monitor(db, name="paused", enabled=False)

    claimed = monitoring.claim_due_monitors(db, NOW)
    assert [c.monitor_id for c in claimed] == [due.id]
    assert claimed[0].countdown_s == 0  # on time: no jitter
    assert claimed[0].expires_s == 60

    db.refresh(due)
    assert due.next_check_at == NOW + timedelta(seconds=60)
    assert monitoring.claim_due_monitors(db, NOW) == []  # not due again yet


def test_claim_adds_jitter_when_catching_up(db):
    _monitor(db, next_check_at=NOW - timedelta(hours=1))
    (claimed,) = monitoring.claim_due_monitors(db, NOW)
    assert 0 <= claimed.countdown_s <= monitoring.MAX_CATCH_UP_JITTER_S


def test_state_machine_down_after_threshold_then_recovers(db):
    m = _monitor(db)

    assert monitoring.record_result(db, m.id, OK, NOW) == []
    db.refresh(m)
    assert m.state == "UP"

    assert monitoring.record_result(db, m.id, FAIL, NOW) == []  # 1 failure: still UP
    db.refresh(m)
    assert (m.state, m.consecutive_failures) == ("UP", 1)

    (down_alert,) = monitoring.record_result(db, m.id, FAIL, NOW + timedelta(minutes=1))
    db.refresh(m)
    assert m.state == "DOWN"
    incident = db.query(Incident).one()
    assert incident.kind == "down" and incident.ended_at is None
    assert incident.cause == "unexpected status 503"
    assert db.get(Alert, down_alert).kind == "down"

    assert monitoring.record_result(db, m.id, FAIL, NOW + timedelta(minutes=2)) == []  # no spam

    (recovered,) = monitoring.record_result(db, m.id, OK, NOW + timedelta(minutes=5))
    db.refresh(m)
    db.refresh(incident)
    assert m.state == "UP" and m.consecutive_failures == 0
    assert incident.ended_at == NOW + timedelta(minutes=5)
    assert db.get(Alert, recovered).kind == "recovered"
    assert db.query(CheckResult).count() == 5


def test_record_result_for_deleted_monitor_is_noop(db, migrated_db):
    assert monitoring.record_result(db, 999, OK, NOW) == []


def test_tls_expiry_opens_one_incident_and_closes_on_renewal(db):
    m = _monitor(db)
    soon = NOW + timedelta(days=5)
    (alert_id,) = monitoring.record_tls_expiry(db, m.id, soon, NOW, warning_days=14)
    assert db.get(Alert, alert_id).kind == "tls_expiring"
    assert monitoring.record_tls_expiry(db, m.id, soon, NOW + timedelta(days=1), 14) == []

    renewed = NOW + timedelta(days=90)
    assert monitoring.record_tls_expiry(db, m.id, renewed, NOW + timedelta(days=2), 14) == []
    incident = db.query(Incident).one()
    assert incident.ended_at is not None
    db.refresh(m)
    assert m.tls_expires_at == renewed


def _down_alert(db) -> int:
    m = _monitor(db)
    monitoring.record_result(db, m.id, FAIL, NOW)
    (alert_id,) = monitoring.record_result(db, m.id, FAIL, NOW)
    return alert_id


def test_send_alert_not_configured_marks_failed(db, monkeypatch):
    alert_id = _down_alert(db)
    assert tasks.send_alert(alert_id) == "failed"
    db.expire_all()
    alert = db.get(Alert, alert_id)
    assert alert.status == "failed" and "SMTP_HOST" in alert.last_error


def test_send_alert_sends_once(db, monkeypatch):
    alert_id = _down_alert(db)
    sent = []
    monkeypatch.setattr(alerts, "send", lambda message, settings: sent.append(message))

    assert tasks.send_alert(alert_id) == "sent"
    assert tasks.send_alert(alert_id) == "skipped"
    assert len(sent) == 1
    assert sent[0]["Subject"] == "[DOWN] site"
    db.expire_all()
    alert = db.get(Alert, alert_id)
    assert alert.status == "sent" and alert.sent_at is not None and alert.attempts == 1


def test_run_check_records_and_queues_alert(db, monkeypatch):
    m = _monitor(db, failure_threshold=1)
    monkeypatch.setattr(tasks.checks, "run", lambda *a: FAIL)
    queued = []
    monkeypatch.setattr(tasks.send_alert, "delay", lambda alert_id: queued.append(alert_id))

    tasks.run_check(m.id)
    db.refresh(m)
    assert m.state == "DOWN"
    assert len(queued) == 1


def test_schedule_due_checks_uses_lock(db, redis_client, monkeypatch):
    _monitor(db)
    calls = []
    monkeypatch.setattr(tasks.run_check, "apply_async", lambda **kw: calls.append(kw))
    monkeypatch.setattr(monitoring, "utcnow", lambda: NOW)

    assert tasks.schedule_due_checks() == 1
    assert calls[0]["expires"] == 60
    assert tasks.schedule_due_checks() == 0  # lock held for this cycle


@pytest.mark.parametrize("kind", ["down", "recovered", "tls_expiring"])
def test_compose_subjects(db, kind):
    m = _monitor(db)
    incident = Incident(monitor_id=m.id, kind="down", started_at=NOW, ended_at=NOW, cause="x")
    db.add(incident)
    db.commit()
    alert = Alert(incident_id=incident.id, kind=kind)
    message = alerts.compose(db, alert, alerts.Settings())
    assert "site" in message["Subject"]
