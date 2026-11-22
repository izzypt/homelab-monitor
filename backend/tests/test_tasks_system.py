import httpx

from app.config import get_settings
from app.tasks import system


def test_ping_disabled_when_url_unset(monkeypatch):
    monkeypatch.setattr(get_settings(), "healthcheck_ping_url", "")
    assert system.ping_healthcheck() is False


def test_ping_success(monkeypatch):
    monkeypatch.setattr(get_settings(), "healthcheck_ping_url", "https://hc.example/abc")

    def ok(url, timeout):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(system.httpx, "get", ok)
    assert system.ping_healthcheck() is True


def test_ping_failure_never_raises(monkeypatch):
    monkeypatch.setattr(get_settings(), "healthcheck_ping_url", "https://hc.example/abc")

    def boom(url, timeout):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(system.httpx, "get", boom)
    assert system.ping_healthcheck() is False
