"""Email alerts over SMTP."""

import logging
import smtplib
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Alert, BootEvent, Host, Incident, Monitor

log = logging.getLogger(__name__)


class AlertingNotConfigured(Exception):
    pass


def compose(db: Session, alert: Alert, settings: Settings) -> EmailMessage:
    incident = db.get(Incident, alert.incident_id) if alert.incident_id else None
    boot = db.get(BootEvent, alert.boot_event_id) if alert.boot_event_id else None
    monitor = db.get(Monitor, incident.monitor_id) if incident and incident.monitor_id else None
    host_id = (incident.host_id if incident else None) or (boot.host_id if boot else None)
    host = db.get(Host, host_id) if host_id else None
    name = monitor.name if monitor else host.name if host else "homelab"
    tz = ZoneInfo(settings.timezone)

    if alert.kind == "unexpected_reboot" and boot:
        subject = f"[REBOOT] {name} restarted unexpectedly"
        minutes = f"{boot.downtime_s // 60} min" if boot.downtime_s is not None else "unknown"
        body = (
            f"{name} came back up at {boot.boot_time.astimezone(tz):%Y-%m-%d %H:%M %Z} "
            f"after an unexpected shutdown (macOS cause code {boot.shutdown_cause_code}).\n"
            f"Approximate downtime: {minutes}.\n"
        )
    elif alert.kind == "down" and incident and host:
        subject = f"[DOWN] {name}: no heartbeat"
        body = (
            f"The host agent on {name} stopped reporting. {incident.cause}.\n"
            "If the whole machine is down, the healthchecks.io pings will report it too.\n"
        )
    elif alert.kind == "disk_high" and incident:
        subject = f"[DISK] {name}: {incident.cause}"
        body = f"{name}: {incident.cause}.\n"
    elif alert.kind == "down" and incident:
        subject = f"[DOWN] {name}"
        body = (
            f"{name} is DOWN since {incident.started_at.astimezone(tz):%Y-%m-%d %H:%M %Z}.\n"
            f"Target: {monitor.target if monitor else '-'}\n"
            f"Reason: {incident.cause or 'unknown'}\n"
        )
    elif alert.kind == "recovered" and incident:
        subject = f"[RECOVERED] {name}"
        duration = (incident.ended_at or incident.started_at) - incident.started_at
        minutes = int(duration.total_seconds() // 60)
        body = f"{name} is back UP after {minutes} min of downtime.\n"
    elif alert.kind == "tls_expiring" and incident:
        subject = f"[TLS] {name}: certificate expiring"
        body = f"{name}: {incident.cause}.\nTarget: {monitor.target if monitor else '-'}\n"
    else:
        subject = f"[{alert.kind.upper()}] {name}"
        body = incident.cause if incident and incident.cause else alert.kind

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_from
    message["To"] = ", ".join(settings.alert_recipient_list)
    message.set_content(body + "\n-- homelab-monitor\n")
    return message


def send(message: EmailMessage, settings: Settings) -> None:
    if not (settings.smtp_host and settings.alert_from and settings.alert_recipient_list):
        raise AlertingNotConfigured("SMTP_HOST, ALERT_FROM and ALERT_RECIPIENTS must be set")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
