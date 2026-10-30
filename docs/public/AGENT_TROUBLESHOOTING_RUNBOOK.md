# Patch-SecOps Solution Agent Troubleshooting Runbook

## Scope

This runbook covers real production issues that occurred with Windows and Linux agents and the exact remediation steps.

## 1) Symptoms Seen

- Host showed `ONLINE` but `API UNREACHABLE` in Host Inventory.
- `curl http://127.0.0.1:8080/health` returned `Internal Server Error`.
- `curl http://127.0.0.1:9100/metrics` failed with connection errors.
- Grafana showed only one agent when two agents were registered.
- Reinstall attempts succeeded but behavior did not change.

## 2) Root Causes Found

- Wrong installer artifact was served from `/opt/patchmaster/backend/static` while a newer fixed artifact existed in another path.
- Windows agent executable had runtime packaging mismatch in some builds.
- Local port conflicts (`wslrelay.exe`, stale listeners) blocked agent API/metrics ports.
- `master-url` values were sometimes entered with backticks in PowerShell.
- Duplicate agents with the same IP required distinct metrics targets (`:9100`, `:9101`) to show separately in Grafana.

## 3) Permanent Code Fixes Applied

- Hardened Windows installer URL normalization and reinstall behavior:
  - `agent/windows_installer.py`
- Hardened health endpoint to avoid 500 from non-critical checks:
  - `agent/agent.py`
- Switched Windows artifact default to onefile to avoid missing `_internal/python*.dll` runtime failures:
  - `agent/build_agent_artifacts.py`
- Fixed backend register timestamp mismatch (`naive` vs `aware` datetime):

## 4) Windows Installer Pre-Config (Recommended)

- Open **PowerShell as Administrator**.
- Do not use backticks around URL values.
- Download installer:
  - `curl.exe -L -o PatchMaster-Agent-Installer.exe "http://172.24.51.176:3000/download/patchmaster-agent-installer.exe"`
- Install in standard mode (robust startup checks, non-strict health):
  - `.\PatchMaster-Agent-Installer.exe --master-url "http://172.24.51.176:8000" --agent-port 18080`
- If you want strict install validation:
  - `.\PatchMaster-Agent-Installer.exe --master-url "http://172.24.51.176:8000" --strict-health`

The installer now waits longer for first boot and accepts startup when API port is open even if `/health` is not ready yet.
Default Windows dedicated agent API port is `18080` (to avoid 8080 conflicts with other tools).
  - `backend/api/register_v2.py`
- Improved Prometheus target sync for duplicate-IP mixed OS environments by adding additional metrics ports:
  - `backend/prometheus_targets.py`

## 4) Windows Firewall Rules (Required)

Run as Administrator:

```powershell
netsh advfirewall firewall add rule name="Patch-SecOps Solution API 8080 In" dir=in action=allow protocol=TCP localport=8080 profile=any
netsh advfirewall firewall add rule name="Patch-SecOps Solution Metrics 9100 In" dir=in action=allow protocol=TCP localport=9100 profile=any
netsh advfirewall firewall add rule name="Patch-SecOps Solution Metrics 9101 In" dir=in action=allow protocol=TCP localport=9101 profile=any
```

## 5) Windows Port Proxy (WSL / Same-IP Dual Agent Scenario)

If Windows and Linux agents share one reachable host IP, expose Linux metrics via another port:

```powershell
Set-Service iphlpsvc -StartupType Automatic
Start-Service iphlpsvc

netsh interface portproxy add v4tov4 listenaddress=<WINDOWS_IP> listenport=9100 connectaddress=127.0.0.1 connectport=9100
netsh interface portproxy add v4tov4 listenaddress=<WINDOWS_IP> listenport=9101 connectaddress=127.0.0.1 connectport=9101
netsh interface portproxy show all
```

## 6) Linux Agent Port Settings for Dual-Agent Same-IP

On Linux agent host:

```bash
sudo sed -i 's/^AGENT_PORT=.*/AGENT_PORT=18080/' /etc/patch-agent/env
sudo sed -i 's/^METRICS_PORT=.*/METRICS_PORT=9101/' /etc/patch-agent/env
sudo systemctl restart patch-agent patch-agent-heartbeat || sudo systemctl restart patch-agent-api patch-agent
```

## 7) Artifact Integrity Verification (Critical)

Server must serve the same hash as local build:

```bash
sha256sum /opt/patchmaster/backend/static/patchmaster-agent-installer.exe
curl -fSL http://127.0.0.1:3000/download/patchmaster-agent-installer.exe -o /tmp/pm-installer.exe
sha256sum /tmp/pm-installer.exe
```

If hashes differ, copy updated artifacts into `/opt/patchmaster/backend/static/` and restart services.

## 8) Final Validation Checklist

Windows:

```powershell
curl.exe -sS http://127.0.0.1:8080/health
curl.exe -sS http://127.0.0.1:9100/metrics | Select-Object -First 10
```

Server:

```bash
curl -sS --max-time 5 http://<WINDOWS_IP>:8080/health
curl -sS --max-time 5 http://<WINDOWS_IP>:9100/metrics | head
curl -sS --max-time 5 http://<WINDOWS_IP>:9101/metrics | head
curl -sS "http://127.0.0.1:9090/api/monitoring/embed/prometheus/api/v1/query?query=up%7Bjob%3D%22patchmaster-agents%22%7D"
```

Expected:

- Health endpoint returns JSON `status: ok`
- Metrics endpoints return Prometheus text
- `up{job="patchmaster-agents"}` shows all expected instances
