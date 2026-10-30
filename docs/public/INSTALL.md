# Patch-SecOps Solution Installation & Operations Guide

Audience: end users deploying Patch-SecOps Solution, installing/uninstalling agents, and enabling monitoring.

## 1) Master Install

**Option A — Docker (recommended)**

```bash
cd /mnt/c/Users/test/Desktop/pat-1
cp .env.production .env && nano .env        # set secrets/DB creds/ports
make prod                                   # core stack
make prod-monitoring                        # core stack + Prometheus+Grafana
```

**Option B — Bare-metal (Ubuntu/Debian/RHEL)**

```bash
cd /mnt/c/Users/test/Desktop/pat-1/packaging
sudo ./install-bare.sh --with-monitoring
# or: sudo ./install-bare.sh --env /path/to/real.env --with-monitoring
# add --ssl-cert/--ssl-key if you have certificates
```

**Verify master**

```bash
curl http://<server-ip>:8000/health
curl http://<server-ip>:8000/metrics         # Prometheus endpoint
docker compose ps                            # if using Docker
sudo systemctl status patchmaster-backend    # if bare-metal
```

## 2) Master Uninstall

- Docker: `cd /mnt/c/Users/test/Desktop/pat-1 && docker compose down -v` (removes containers/volumes).
- Bare-metal: stop services and remove install dir if acceptable:
  ```bash
  sudo systemctl stop patchmaster-backend patchmaster-frontend prometheus grafana || true
  sudo rm -rf /opt/patchmaster
  ```

## 3) Agent Install

## 3A) PoC Prerequisites (Networking)

Patch-SecOps Solution has two data paths:

- Host inventory/online status comes from the agent registering + heartbeating to the Patch-SecOps Solution backend.
- Grafana Host Details comes from Prometheus scraping the agent metrics endpoint.

Minimum required network flows:

- Agent host → Patch-SecOps Solution server: TCP 8000 (register/heartbeat + API)
- Patch-SecOps Solution server → Agent host: TCP 9100 (Prometheus scrape for Grafana Host Details)
- Patch-SecOps Solution server → Agent host: TCP 8080 (agent API for patching/commands)

If the second path (server → host 9100) is blocked, the host can still show ONLINE in Patch-SecOps Solution but Grafana Host Details will show No data.

Linux firewall examples:

```bash
# ufw
sudo ufw allow 9100/tcp

# firewalld
sudo firewall-cmd --add-port=9100/tcp --permanent
sudo firewall-cmd --reload
```

Windows firewall example (run as Administrator):

```powershell
New-NetFirewallRule -DisplayName "Patch-SecOps Solution Agent Metrics" -Direction Inbound -Protocol TCP -LocalPort 9100 -Action Allow
New-NetFirewallRule -DisplayName "Patch-SecOps Solution Agent API" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
```

**Windows (Admin CMD/PowerShell)**

```bat
curl.exe -L -o PatchMaster-Agent-Installer.exe http://<master-ip>:3000/download/patchmaster-agent-installer.exe
PatchMaster-Agent-Installer.exe --master-url http://<master-ip>:8000 --no-pause
```

Air-gapped Windows note: the PatchMaster-Agent-Installer.exe is self-contained and does not require Python or internet access on the agent host. Ensure TCP 9100 (metrics) and TCP 8080 (agent API) are allowed inbound from the Patch-SecOps Solution server if those features are used.

**Debian/Ubuntu**

```bash
curl -fsSL -o agent-latest.deb http://<master-ip>:3000/download/agent-latest.deb
sudo dpkg -i agent-latest.deb
echo 'CONTROLLER_URL=http://<master-ip>:8000' | sudo tee /etc/patch-agent/env
sudo systemctl enable --now patch-agent patch-agent-heartbeat
```

Air-gapped Linux note: the agent .deb/.rpm bundles its Python runtime dependencies and does not require internet access on the agent host.

**RHEL/CentOS/Rocky/Alma**

```bash
curl -fsSL -o agent-latest.rpm http://<master-ip>:3000/download/agent-latest.rpm
sudo rpm -Uvh agent-latest.rpm || sudo dnf localinstall -y agent-latest.rpm
echo 'CONTROLLER_URL=http://<master-ip>:8000' | sudo tee /etc/patch-agent/env
sudo systemctl enable --now patch-agent patch-agent-heartbeat
```

### Air‑Gapped Checklist (Linux)
- Ensure outbound from agent to Patch-SecOps Solution: TCP 8000.
- Ensure inbound to agent from Patch-SecOps Solution: TCP 9100 (metrics) and TCP 8080 (agent API, if used).
- Verify services:
  ```bash
  sudo systemctl status patch-agent patch-agent-heartbeat
  ```
- Verify local agent endpoints:
  ```bash
  curl -sS http://127.0.0.1:9100/metrics | head
  curl -sS http://127.0.0.1:8080/health
  ```
- Verify server scrape status (run on Patch-SecOps Solution server):
  ```bash
  curl -g 'http://127.0.0.1:9090/api/monitoring/embed/prometheus/api/v1/query?query=up{job="patchmaster-agents"}'
  ```
- If scrape shows 0, open firewall and confirm network path; on ufw:
  ```bash
  sudo ufw allow 9100/tcp
  ```

**Agent verification**

```bash
sudo systemctl status patch-agent patch-agent-heartbeat
curl http://localhost:8080/health
curl http://localhost:9100/metrics
```

## 4) Agent Uninstall

- Windows: `PatchMaster-Agent-Installer.exe --uninstall --no-pause` (run as Admin).
- Linux: `sudo /opt/patch-agent/uninstall.sh` (packaged helper) or `sudo patch-agent-uninstall` if the wrapper exists.
- Full product purge (remove all Patch-SecOps Solution app/data artifacts): `sudo bash scripts/uninstall_patchmaster.sh --purge-all --force`

## 5) Monitoring

- If installed with monitoring (`make prod-monitoring` or `--with-monitoring`), Prometheus and Grafana run automatically; Grafana default port: :3001.
- To use an existing Prometheus, add targets:

```yaml
scrape_configs:
  - job_name: 'patchmaster'
    metrics_path: /metrics
    static_configs: [{ targets: ['<server-ip>:8000'] }]
  - job_name: 'patchmaster-agents'
    static_configs: [{ targets: ['<host1>:9100','<host2>:9100'] }]
```

- Import Grafana dashboard JSON:
  `/mnt/c/Users/test/Desktop/pat-1/monitoring/grafana/dashboards/patchmaster-overview.json`

## 6) Quick Health Checks

```bash
curl http://<server-ip>:8000/health
curl http://<server-ip>:8000/metrics
docker compose logs -f backend                 # Docker
sudo journalctl -u patchmaster-backend -f      # Bare-metal
```

## 7) Release Build (optional)

```bash
cd /mnt/c/Users/test/Desktop/pat-1
bash packaging/build-package.sh --output dist/
# Output: dist/patchmaster-2.0.0.tar.gz
```

For fully offline Ubuntu 22.04 / Python 3.10 installs, validate the wheelhouse first:

```bash
python3 scripts/manage_offline_wheels.py check --profile linux-py310
# with internet access, populate missing wheels:
python3 scripts/manage_offline_wheels.py download --profile linux-py310
```
