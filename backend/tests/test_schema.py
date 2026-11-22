import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Alert, Host, Incident, Monitor


def _monitor(**kw) -> Monitor:
    return Monitor(name=kw.pop("name", "site"), type="http", target="https://example.com", **kw)


def test_monitor_defaults(db):
    m = _monitor()
    db.add(m)
    db.commit()
    db.refresh(m)
    assert (m.state, m.interval_s, m.timeout_s, m.failure_threshold, m.enabled) == (
        "PENDING",
        60,
        10,
        2,
        True,
    )
    assert m.config == {}


@pytest.mark.parametrize(
    "fields",
    [{"type": "ftp"}, {"interval_s": 5}, {"timeout_s": 60}, {"state": "MAYBE"}],
)
def test_monitor_check_constraints(db, fields):
    m = _monitor()
    for k, v in fields.items():
        setattr(m, k, v)
    db.add(m)
    with pytest.raises(IntegrityError):
        db.commit()


def test_incident_needs_exactly_one_subject(db):
    host = Host(name="mac-mini", agent_token_hash="x" * 64)
    m = _monitor()
    db.add_all([host, m])
    db.commit()

    db.add(Incident())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(Incident(monitor_id=m.id, host_id=host.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(Incident(monitor_id=m.id))
    db.commit()


def test_alert_is_unique_per_incident_and_kind(db):
    m = _monitor()
    db.add(m)
    db.commit()
    incident = Incident(monitor_id=m.id)
    db.add(incident)
    db.commit()

    db.add(Alert(incident_id=incident.id, kind="down"))
    db.commit()
    db.add(Alert(incident_id=incident.id, kind="down"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(Alert(incident_id=incident.id, kind="recovered"))
    db.commit()


def test_deleting_monitor_cascades(db):
    m = _monitor()
    db.add(m)
    db.commit()
    db.add(Incident(monitor_id=m.id))
    db.commit()
    db.delete(m)
    db.commit()
    assert db.query(Incident).count() == 0
