import json
import sys
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homelab_agent as agent  # noqa: E402

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100000.
Pages active:                             200000.
Pages inactive:                           150000.
Pages wired down:                         100000.
Pages occupied by compressor:              50000.
"""


def test_parse_boottime():
    out = "{ sec = 1763800000, usec = 123456 } Sat Nov 22 08:26:40 2025\n"
    assert agent.parse_boottime(out) == datetime.fromtimestamp(1763800000, UTC)
    with pytest.raises(ValueError):
        agent.parse_boottime("garbage")


def test_parse_vm_stat():
    total = 1_000_000 * 16384  # 1M pages
    assert agent.parse_vm_stat(VM_STAT, total) == 35.0  # (200k + 100k + 50k) / 1M


def test_parse_launchctl_running():
    assert agent.parse_launchctl_running("system/com.x = {\n\tstate = running\n\tpid = 1\n}")
    assert not agent.parse_launchctl_running("system/com.x = {\n\tstate = not running\n}")


def test_parse_shutdown_cause_takes_last():
    out = (
        "2026-11-20 kernel: Previous shutdown cause: 5\n"
        "2026-11-22 kernel: Previous shutdown cause: -128\n"
    )
    assert agent.parse_shutdown_cause(out) == -128
    assert agent.parse_shutdown_cause("nothing here") is None


def test_config_requires_token(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"api_url": "http://127.0.0.1:8380", "token": ""}))
    with pytest.raises(ValueError):
        agent.Config.load(str(path))
    path.write_text(json.dumps({"api_url": "http://x", "token": "t", "unknown_key": 1}))
    assert agent.Config.load(str(path)).interval_s == 30


def test_spool_caps_and_skips_corrupt_lines(tmp_path):
    spool = agent.Spool(tmp_path / "spool.jsonl", max_items=3)
    spool.write([{"n": i} for i in range(5)])
    assert spool.read() == [{"n": 2}, {"n": 3}, {"n": 4}]
    with spool.path.open("a") as f:
        f.write('{"truncat')
    assert len(spool.read()) == 3


def _config(tmp_path):
    return agent.Config(api_url="http://127.0.0.1:8380/", token="t", state_dir=str(tmp_path))  # noqa: S106


def test_deliver_sends_backlog_then_clears(tmp_path):
    spool = agent.Spool(tmp_path / "s.jsonl")
    spool.write([{"n": 1}, {"n": 2}])
    sent = []
    ok = agent.deliver(
        _config(tmp_path), spool, {"n": 3}, sender=lambda u, t, p: sent.append((u, p))
    )
    assert ok
    assert sent == [
        (
            "http://127.0.0.1:8380/api/v1/agent/heartbeat",
            {"heartbeats": [{"n": 1}, {"n": 2}, {"n": 3}]},
        )
    ]
    assert spool.read() == []


def test_deliver_buffers_when_unreachable(tmp_path):
    spool = agent.Spool(tmp_path / "s.jsonl")

    def down(url, token, payload):
        raise urllib.error.URLError("connection refused")

    assert not agent.deliver(_config(tmp_path), spool, {"n": 1}, sender=down)
    assert not agent.deliver(_config(tmp_path), spool, {"n": 2}, sender=down)
    assert spool.read() == [{"n": 1}, {"n": 2}]


def test_deliver_keeps_unsent_batches_only(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "BATCH_MAX", 2)
    spool = agent.Spool(tmp_path / "s.jsonl")
    spool.write([{"n": 1}, {"n": 2}, {"n": 3}])
    calls = []

    def flaky(url, token, payload):
        calls.append(payload)
        if len(calls) == 2:
            raise urllib.error.URLError("dropped")

    assert not agent.deliver(_config(tmp_path), spool, {"n": 4}, sender=flaky)
    assert spool.read() == [{"n": 3}, {"n": 4}]  # first batch was delivered, not resent


@pytest.mark.parametrize(("code", "kept"), [(422, 0), (401, 1), (503, 1)])
def test_deliver_http_errors(tmp_path, code, kept):
    spool = agent.Spool(tmp_path / "s.jsonl")

    def reject(url, token, payload):
        raise urllib.error.HTTPError(url, code, "x", {}, None)

    assert not agent.deliver(_config(tmp_path), spool, {"n": 1}, sender=reject)
    assert len(spool.read()) == kept
