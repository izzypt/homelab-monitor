import socket

import dns.exception
import httpx
import pytest

from app import checks


def _transport(status=200, text="all good", exc=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc
        return httpx.Response(status, text=text)

    return httpx.MockTransport(handler)


def test_http_ok():
    outcome = checks.check_http("https://example.com", {}, 5, transport=_transport())
    assert outcome.ok and outcome.status_code == 200 and outcome.latency_ms is not None


def test_http_unexpected_status():
    outcome = checks.check_http("https://example.com", {}, 5, transport=_transport(503))
    assert not outcome.ok
    assert outcome.status_code == 503
    assert outcome.error == "unexpected status 503"


def test_http_expected_status_list():
    cfg = {"expected_status": [401]}
    assert checks.check_http("https://x.test", cfg, 5, transport=_transport(401)).ok
    assert not checks.check_http("https://x.test", cfg, 5, transport=_transport(200)).ok


def test_http_keyword():
    assert checks.check_http("https://x.test", {"keyword": "good"}, 5, transport=_transport()).ok
    outcome = checks.check_http("https://x.test", {"keyword": "zzz"}, 5, transport=_transport())
    assert not outcome.ok and outcome.error == "keyword not found"


def test_http_timeout_and_connect_errors_are_results():
    timeout = _transport(exc=httpx.ReadTimeout("slow"))
    assert checks.check_http("https://x.test", {}, 5, transport=timeout).error == "timeout"
    refused = _transport(exc=httpx.ConnectError("refused"))
    outcome = checks.check_http("https://x.test", {}, 5, transport=refused)
    assert not outcome.ok and "refused" in outcome.error


class _Record:
    def __init__(self, text):
        self.text = text

    def to_text(self):
        return self.text


class _Resolver:
    def __init__(self, records=None, exc=None):
        self.records, self.exc = records or [], exc

    def resolve(self, target, record_type, lifetime):
        if self.exc:
            raise self.exc
        return [_Record(r) for r in self.records]


def test_dns_ok_and_expected_value():
    resolver = _Resolver(["192.0.2.10"])
    assert checks.check_dns("example.com", {}, 5, resolver=resolver).ok
    assert checks.check_dns("example.com", {"expected": "192.0.2.10"}, 5, resolver=resolver).ok
    wrong = checks.check_dns("example.com", {"expected": "192.0.2.99"}, 5, resolver=resolver)
    assert not wrong.ok and "expected" in wrong.error


def test_dns_failures():
    timeout = checks.check_dns("x.test", {}, 5, resolver=_Resolver(exc=dns.exception.Timeout()))
    assert timeout.error == "timeout"
    nx = checks.check_dns("x.test", {}, 5, resolver=_Resolver(exc=dns.exception.DNSException("nx")))
    assert not nx.ok


def test_tcp_open_and_closed_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    try:
        assert checks.check_tcp(f"127.0.0.1:{port}", {}, 2).ok
    finally:
        server.close()
    assert not checks.check_tcp(f"127.0.0.1:{port}", {}, 2).ok


@pytest.mark.parametrize("target", ["nohost", "host:", ":22", "host:abc", "host:70000"])
def test_split_host_port_rejects_bad_targets(target):
    with pytest.raises(ValueError):
        checks.split_host_port(target)


def test_split_host_port_ipv6():
    assert checks.split_host_port("[::1]:5432") == ("::1", 5432)
