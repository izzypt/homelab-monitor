#!/bin/sh
# Install or update the homelab-monitor host agent as a macOS LaunchDaemon.
#
#   sudo ./agent/install.sh --user <agent-user> [--python /opt/homebrew/bin/python3]
#
# Safe to re-run: it updates the script and plist, and never overwrites an existing config.
set -eu

AGENT_USER=""
PYTHON="/opt/homebrew/bin/python3"
LABEL="com.homelab.agent"
HERE="$(cd "$(dirname "$0")" && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --user) AGENT_USER="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -n "$AGENT_USER" ] || { echo "--user is required" >&2; exit 2; }
id "$AGENT_USER" >/dev/null 2>&1 || { echo "user $AGENT_USER does not exist" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "python not found at $PYTHON (use --python)" >&2; exit 1; }

install -d -o root -g wheel -m 755 /usr/local/lib/homelab-agent /usr/local/etc
install -d -o "$AGENT_USER" -m 700 /usr/local/var/homelab-agent
install -d -o "$AGENT_USER" -m 755 /usr/local/var/log
install -o root -g wheel -m 755 "$HERE/homelab_agent.py" /usr/local/lib/homelab-agent/

CONFIG=/usr/local/etc/homelab-agent.json
if [ ! -f "$CONFIG" ]; then
  install -o "$AGENT_USER" -m 600 "$HERE/homelab-agent.example.json" "$CONFIG"
  echo "Created $CONFIG: edit it (token, healthcheck_url), then re-run this script."
  exit 0
fi

PLIST="/Library/LaunchDaemons/$LABEL.plist"
sed -e "s|__USER__|$AGENT_USER|" -e "s|__PYTHON__|$PYTHON|" "$HERE/$LABEL.plist" > "$PLIST"
chown root:wheel "$PLIST"
chmod 644 "$PLIST"

launchctl bootout "system/$LABEL" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
echo "Installed. Status:"
launchctl print "system/$LABEL" | grep -E "state|pid" || true
echo "Logs: tail -f /usr/local/var/log/homelab-agent.log"
