# Host agent (macOS)

Runs natively on the Mac mini, outside Colima, and reports what containers can't see: boot time, uptime, the cause of the previous shutdown, load, memory, disk, and whether the Colima and cloudflared LaunchDaemons are running. See README sections 5.2 and 5.7.

- Python standard library only, with no packages to install. Homebrew's `python3` works.
- Started at boot by a LaunchDaemon (`com.homelab.agent`) as a dedicated non-admin user, and restarted by launchd if it exits.
- Every 30 s it POSTs a heartbeat to the API. If the API is unreachable (for example, Colima is down), heartbeats are kept in a local spool (up to ~1 h) and sent as a batch when the API is back.
- It also pings its own healthchecks.io check (`mac-mini`) every cycle, so you get an email if the Mac itself goes quiet.

## Install

1. **Register the host** while logged in to the dashboard (or call the API): `POST /api/v1/hosts` with `{"name": "mac-mini"}`. The response contains `agent_token`. It's shown only once, so copy it now. Use `POST /api/v1/hosts/{id}/rotate-token` if you lose it.
2. **Create the config** (first run of the script copies the example and stops):
   ```bash
   sudo ./agent/install.sh --user <agent-user>
   sudo nano /usr/local/etc/homelab-agent.json   # set token, healthcheck_url, daemon labels
   ```
3. **Install and start** by running the same command again:
   ```bash
   sudo ./agent/install.sh --user <agent-user> --python /opt/homebrew/bin/python3
   tail -f /usr/local/var/log/homelab-agent.log
   ```

Re-run the script after pulling a new version. It never overwrites an existing config.

## Config (`/usr/local/etc/homelab-agent.json`, mode 600)

| Key | Default | Meaning |
|-----|---------|---------|
| `api_url` | `http://127.0.0.1:8380` | The local nginx entry point. Traffic never leaves the Mac. Until nginx lands, use the dev API at `http://127.0.0.1:8000`. |
| `token` | (required) | Agent token from step 1. |
| `interval_s` | `30` | Seconds between heartbeats. |
| `healthcheck_url` | empty | healthchecks.io ping URL for the `mac-mini` check. Empty disables it. |
| `daemons` | `["com.simao.colima", "com.cloudflare"]` | LaunchDaemon labels to report as running or not. |
| `state_dir` | `/usr/local/var/homelab-agent` | Spool and boot state. |
| `disk_path` | `/System/Volumes/Data` | Volume used for disk %. |

## Notes

- The shutdown cause comes from `log show` ("Previous shutdown cause") and is read once per boot. Code `5` is a normal shutdown. Other codes (`0` power loss, `3` forced power-off, negative values for panics) are reported as unexpected and send an email. If the agent user can't read the unified log, the cause is reported as unknown and no reboot email is sent.
- Check the daemon with `sudo launchctl print system/com.homelab.agent`. Stop it with `sudo launchctl bootout system/com.homelab.agent`.
