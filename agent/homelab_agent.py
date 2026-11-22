#!/usr/bin/env python3
"""homelab-monitor host agent for macOS (README sections 5.2 and 5.7).

Runs natively on the Mac (not in Colima), started by a LaunchDaemon. Every 30 s it:
  1. collects boot time, uptime, load, memory, disk and LaunchDaemon status,
  2. POSTs them to the API (with any heartbeats buffered while the API was unreachable),
  3. pings its own healthchecks.io check ("mac-mini").

Standard library only, so it runs on any python3 without installing packages.
Config: JSON file, path from $HOMELAB_AGENT_CONFIG or /usr/local/etc/homelab-agent.json.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
DEFAULT_CONFIG = "/usr/local/etc/homelab-agent.json"
SPOOL_MAX = 120  # ~1 h of heartbeats at 30 s; oldest dropped beyond this
BATCH_MAX = 200  # matches the API limit

log = logging.getLogger("homelab-agent")


# ---------------------------------------------------------------------------- config


@dataclass
class Config:
    api_url: str
    token: str
    interval_s: int = 30
    healthcheck_url: str = ""
    daemons: list[str] = field(default_factory=lambda: ["com.simao.colima", "com.cloudflare"])
    state_dir: str = "/usr/local/var/homelab-agent"
    disk_path: str = "/System/Volumes/Data"

    @classmethod
    def load(cls, path: str) -> Config:
        data = json.loads(Path(path).read_text())
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        config = cls(**known)
        if not config.api_url or not config.token:
            raise ValueError("config needs api_url and token")
        return config


# ---------------------------------------------------------------------------- collection


def run(cmd: list[str], timeout: float = 10) -> str:
    return subprocess.run(  # noqa: S603  (fixed argument lists, no shell)
        cmd, capture_output=True, text=True, timeout=timeout, check=True
    ).stdout


def parse_boottime(output: str) -> datetime:
    """`sysctl -n kern.boottime` -> '{ sec = 1700000000, usec = 123 } Tue Nov 14 ...'."""
    match = re.search(r"sec\s*=\s*(\d+)", output)
    if not match:
        raise ValueError(f"unexpected kern.boottime output: {output!r}")
    return datetime.fromtimestamp(int(match.group(1)), UTC)


def parse_vm_stat(output: str, total_bytes: int) -> float:
    """Used memory % = (active + wired + compressed) pages / total, like Activity Monitor."""
    page_size = int(re.search(r"page size of (\d+) bytes", output).group(1))
    pages: dict[str, int] = {}
    for line in output.splitlines()[1:]:
        key, _, value = line.partition(":")
        value = value.strip().rstrip(".")
        if value.isdigit():
            pages[key.strip()] = int(value)
    used = (
        pages.get("Pages active", 0)
        + pages.get("Pages wired down", 0)
        + pages.get("Pages occupied by compressor", 0)
    )
    return round(100 * used * page_size / total_bytes, 1)


def parse_launchctl_running(output: str) -> bool:
    return bool(re.search(r"^\s*state = running\s*$", output, re.MULTILINE))


def parse_shutdown_cause(output: str) -> int | None:
    """Last 'Previous shutdown cause: N' line from `log show`."""
    matches = re.findall(r"Previous shutdown cause:\s*(-?\d+)", output)
    return int(matches[-1]) if matches else None


def daemon_running(label: str) -> bool:
    try:
        return parse_launchctl_running(run(["/bin/launchctl", "print", f"system/{label}"]))
    except (subprocess.SubprocessError, OSError):
        return False


def shutdown_cause() -> int | None:
    """Reading the unified log is slow, so this runs once per boot, not every heartbeat."""
    try:
        output = run(
            [
                "/usr/bin/log",
                "show",
                "--last",
                "boot",
                "--style",
                "compact",
                "--predicate",
                'eventMessage CONTAINS "Previous shutdown cause"',
            ],
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("could not read shutdown cause: %s", exc)
        return None
    return parse_shutdown_cause(output)


def collect(config: Config, boot_time: datetime, cause: int | None) -> dict[str, Any]:
    now = datetime.now(UTC)
    heartbeat: dict[str, Any] = {
        "collected_at": now.isoformat(),
        "boot_time": boot_time.isoformat(),
        "uptime_s": int((now - boot_time).total_seconds()),
        "load_1m": round(os.getloadavg()[0], 2),
        "daemons": {label: daemon_running(label) for label in config.daemons},
        "agent_version": VERSION,
        "shutdown_cause": cause,
    }
    try:
        total = int(run(["/usr/sbin/sysctl", "-n", "hw.memsize"]).strip())
        heartbeat["mem_used_pct"] = parse_vm_stat(run(["/usr/bin/vm_stat"]), total)
    except (subprocess.SubprocessError, OSError, ValueError, AttributeError) as exc:
        log.warning("memory stats unavailable: %s", exc)
    try:
        usage = shutil.disk_usage(config.disk_path)
        heartbeat["disk_used_pct"] = round(100 * usage.used / usage.total, 1)
    except OSError as exc:
        log.warning("disk stats unavailable: %s", exc)
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        heartbeat["os_version"] = "macOS " + run(["/usr/bin/sw_vers", "-productVersion"]).strip()
    return heartbeat


# ---------------------------------------------------------------------------- spool


class Spool:
    """Heartbeats that could not be delivered, as JSON lines, capped at SPOOL_MAX."""

    def __init__(self, path: Path, max_items: int = SPOOL_MAX) -> None:
        self.path, self.max_items = path, max_items

    def read(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text().splitlines()
        except FileNotFoundError:
            return []
        items = []
        for line in lines:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a partially written line
        return items

    def write(self, items: list[dict[str, Any]]) -> None:
        items = items[-self.max_items :]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(i) + "\n" for i in items))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)  # atomic


# ---------------------------------------------------------------------------- delivery


def post_json(url: str, token: str, payload: dict[str, Any], timeout: float = 10) -> int:
    request = urllib.request.Request(  # noqa: S310  (URL comes from the local config file)
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"homelab-agent/{VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.status


def ping(url: str) -> None:
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).close()  # noqa: S310
    except (urllib.error.URLError, OSError) as exc:
        log.warning("healthcheck ping failed: %s", exc)


def deliver(config: Config, spool: Spool, heartbeat: dict[str, Any], sender=post_json) -> bool:
    """Send the backlog plus this heartbeat in batches. Whatever is not delivered stays spooled."""
    pending = [*spool.read(), heartbeat]
    url = config.api_url.rstrip("/") + "/api/v1/agent/heartbeat"
    sent = 0
    try:
        while sent < len(pending):
            batch = pending[sent : sent + BATCH_MAX]
            sender(url, config.token, {"heartbeats": batch})
            sent += len(batch)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 413, 422):
            # The API will never accept this payload: drop it instead of retrying forever.
            log.error("API rejected heartbeats (%s); dropping %d", exc.code, len(pending) - sent)
            spool.write([])
        else:  # 401/403 (fix the token, history is kept) or 5xx (API trouble)
            log.warning("API error %s; buffering %d heartbeat(s)", exc.code, len(pending) - sent)
            spool.write(pending[sent:])
        return False
    except (urllib.error.URLError, OSError) as exc:
        log.warning("API unreachable (%s); buffering %d heartbeat(s)", exc, len(pending) - sent)
        spool.write(pending[sent:])
        return False
    spool.write([])
    return True


# ---------------------------------------------------------------------------- main loop


class BootState:
    """Remembers which boot we already read the shutdown cause for."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def cause_for(self, boot_time: datetime) -> tuple[int | None, bool]:
        try:
            data = json.loads(self.path.read_text())
            if data.get("boot_time") == boot_time.isoformat():
                return data.get("shutdown_cause"), False
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        cause = shutdown_cause()
        self.path.write_text(
            json.dumps({"boot_time": boot_time.isoformat(), "shutdown_cause": cause})
        )
        return cause, True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Config.load(os.environ.get("HOMELAB_AGENT_CONFIG", DEFAULT_CONFIG))
    state_dir = Path(config.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    spool = Spool(state_dir / "spool.jsonl")
    boot_state = BootState(state_dir / "boot.json")

    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("homelab-agent %s started, reporting to %s", VERSION, config.api_url)

    while not stopping:
        started = time.monotonic()
        try:
            boot_time = parse_boottime(run(["/usr/sbin/sysctl", "-n", "kern.boottime"]))
            cause, new_boot = boot_state.cause_for(boot_time)
            if new_boot:
                log.info("boot at %s, previous shutdown cause %s", boot_time, cause)
            deliver(config, spool, collect(config, boot_time, cause))
            ping(config.healthcheck_url)
        except Exception:  # keep the daemon alive no matter what one cycle does
            log.exception("heartbeat cycle failed")
        while not stopping and time.monotonic() - started < config.interval_s:
            time.sleep(1)
    log.info("homelab-agent stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
