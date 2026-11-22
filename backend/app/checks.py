"""Check executors: one function per monitor type. Pure I/O, no database access.

Each returns a CheckOutcome; failures are results, never exceptions.
"""

import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import dns.exception
import dns.resolver
import httpx

from app.config import get_settings


@dataclass(frozen=True)
class CheckOutcome:
    ok: bool
    latency_ms: int | None = None
    status_code: int | None = None
    error: str | None = None


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _status_ok(code: int, expected: list[int] | None) -> bool:
    return code in expected if expected else 200 <= code < 400


def check_http(
    target: str,
    config: dict[str, Any],
    timeout_s: float,
    transport: httpx.BaseTransport | None = None,
) -> CheckOutcome:
    method = config.get("method", "GET")
    keyword = config.get("keyword")
    start = time.perf_counter()
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=config.get("follow_redirects", True),
            headers={"User-Agent": get_settings().check_user_agent},
            transport=transport,
        ) as client:
            response = client.request(method, target)
    except httpx.TimeoutException:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error="timeout")
    except httpx.HTTPError as exc:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error=_short(exc))

    latency = _elapsed_ms(start)
    if not _status_ok(response.status_code, config.get("expected_status")):
        return CheckOutcome(
            ok=False,
            latency_ms=latency,
            status_code=response.status_code,
            error=f"unexpected status {response.status_code}",
        )
    if keyword and keyword not in response.text:
        return CheckOutcome(
            ok=False,
            latency_ms=latency,
            status_code=response.status_code,
            error="keyword not found",
        )
    return CheckOutcome(ok=True, latency_ms=latency, status_code=response.status_code)


def check_dns(
    target: str,
    config: dict[str, Any],
    timeout_s: float,
    resolver: dns.resolver.Resolver | None = None,
) -> CheckOutcome:
    record_type = config.get("record_type", "A")
    expected = config.get("expected")
    resolver = resolver or dns.resolver.Resolver()
    start = time.perf_counter()
    try:
        answer = resolver.resolve(target, record_type, lifetime=timeout_s)
    except dns.exception.Timeout:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error="timeout")
    except dns.exception.DNSException as exc:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error=_short(exc))

    latency = _elapsed_ms(start)
    values = [r.to_text().rstrip(".") for r in answer]
    if expected and not any(expected.rstrip(".") in v for v in values):
        return CheckOutcome(
            ok=False, latency_ms=latency, error=f"expected {expected!r}, got {values}"
        )
    return CheckOutcome(ok=True, latency_ms=latency)


def split_host_port(target: str) -> tuple[str, int]:
    host, sep, port = target.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError("target must be host:port")
    return host.strip("[]"), int(port)


def check_tcp(target: str, config: dict[str, Any], timeout_s: float) -> CheckOutcome:
    host, port = split_host_port(target)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            pass
    except TimeoutError:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error="timeout")
    except OSError as exc:
        return CheckOutcome(ok=False, latency_ms=_elapsed_ms(start), error=_short(exc))
    return CheckOutcome(ok=True, latency_ms=_elapsed_ms(start))


def run(monitor_type: str, target: str, config: dict[str, Any], timeout_s: float) -> CheckOutcome:
    executors = {"http": check_http, "dns": check_dns, "tcp": check_tcp}
    return executors[monitor_type](target, config, timeout_s)


def tls_expiry(url: str, timeout_s: float = 10) -> datetime:
    """Return the notAfter of the certificate served for an https URL."""
    parts = urlsplit(url)
    host, port = parts.hostname, parts.port or 443
    if parts.scheme != "https" or not host:
        raise ValueError("not an https URL")
    context = ssl.create_default_context()
    with (
        socket.create_connection((host, port), timeout=timeout_s) as sock,
        context.wrap_socket(sock, server_hostname=host) as tls,
    ):
        cert = tls.getpeercert()
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), UTC)


def _short(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    return text[:500]
