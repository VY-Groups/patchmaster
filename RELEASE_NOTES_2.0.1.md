# PatchMaster 2.0.1 Release Notes

**Release Date:** April 16, 2026  
**Package:** `patchmaster-2.0.1.tar.gz` (74.7 MB)  
**Git Commits:** 7c6ddcb and earlier

## Overview

This is a critical bug fix release that addresses deployment issues, WebSocket connectivity, agent registration, and security improvements. All users experiencing installation or agent visibility issues should upgrade to this version.

## Critical Fixes

### 1. WebSocket Connection Issues ✅
**Issue:** Groups & Tags page failing with "WebSocket connection failed" errors

**Fix:**
- Added missing WebSocket proxy headers to nginx configuration
- Added `proxy_http_version 1.1`
- Added `proxy_set_header Upgrade $http_upgrade`
- Added `proxy_set_header Connection "upgrade"`
- Increased proxy timeouts for long-lived connections

**Impact:** Groups & Tags page now works correctly, real-time notifications functional

### 2. Agent Registration & Visibility ✅
**Issue:** Agents installed but not appearing in PatchMaster UI

**Fix:**
- Created comprehensive agent registration fix script
- Improved agent service configuration handling
- Added connectivity testing and verification
- Enhanced error messages and troubleshooting guidance

**Impact:** Agents now register and appear in UI reliably

### 3. Offline Agent Installation ✅ NEW
**Issue:** Agents requiring internet to download Python packages during installation

**Fix:**
- Agent package now includes all Python dependencies bundled in virtualenv
- Uses local wheels from `vendor/wheels/` directory
- No internet required on target hosts
- Truly self-contained package (~35 MB)

**Impact:** Agents can be installed on air-gapped/offline systems without any issues

**Included Dependencies:**
- Flask (web framework)
- prometheus_client (metrics)
- psutil (system info)
- requests (HTTP client)
- PyYAML (config parsing)
- All transitive dependencies

### 4. Database Initialization Feedback ✅
**Issue:** Installation hanging with no feedback during database initialization

**Fix:**
- Added clear success/warning/error messages during schema creation
- Graceful handling of existing database objects (upgrades)
- Better error reporting for actual failures

**Impact:** Installation process provides clear feedback, handles upgrades gracefully

### 4. Security Improvements ✅

#### Hardcoded Default Passwords
**Issue:** PostgreSQL and Grafana using weak default password "patchmaster"

**Fix:**
- PostgreSQL: `PgPm!7` + 16 random hex chars (e.g., `PgPm!7a3f8e9c1d2b4567`)
- Grafana: `GfA!7` + 16 random hex chars (e.g., `GfA!79f2e1a8c7d6b543`)
- Uses `secrets.token_hex(8)` for cryptographically secure random generation

**Impact:** New installations have strong, unique passwords

#### Weak Password Detection
**Issue:** Limited weak password list (only 6 passwords)

**Fix:**
- Expanded from 6 to 30 common weak passwords
- Includes: password123, admin1, root, toor, qwerty, abc123, letmein, welcome, monkey, dragon, master, sunshine, princess, football, shadow, and 15 more

**Impact:** Better protection against weak password usage

#### Bare Exception Clauses
**Issue:** 20+ instances of bare `except:` catching all exceptions including system exits

**Fix:**
- Replaced all bare except clauses with specific exception types
- File operations: `except (IOError, OSError):`
- JSON parsing: `except (json.JSONDecodeError, ValueError):`
- Added descriptive comments to all exception handlers

**Files Fixed:**
- `agent/agent.py` (15 instances)
- `agent/solaris_manager.py`
- `agent/aix_manager.py`
- `agent/hpux_manager.py`
- `agent/patchrepo_api.py`
- `backend/api/agent_proxy.py`

**Impact:** Better error handling, prevents catching system exits

### 5. Canary Testing Full Rollout ✅
**Issue:** TODO comment in canary_testing.py with no implementation

**Fix:**
- Implemented `_trigger_full_rollout()` function
- Automatically deploys to remaining hosts after canary success
- Includes error handling for individual host failures
- Stores rollout job IDs and timestamp in run metadata
- Added comprehensive logging

**Impact:** Canary testing workflow now complete and functional

## New Tools & Scripts

### Fix Scripts (Included in Package)

1. **fix_websocket_and_groups.sh** (Run on server)
   - Fixes WebSocket connections and Groups & Tags page
   - Backs up nginx config before changes
   - Tests and reloads nginx safely
   - Verifies backend service and API endpoints

2. **fix_agent_registration.sh** (Run on agent)
   - Fixes agent registration and visibility issues
   - Configures CONTROLLER_URL properly
   - Restarts services cleanly
   - Verifies connectivity and registration

3. **diagnose_agent_issues.sh** (Run on server)
   - Comprehensive system diagnostics
   - Checks all services and endpoints
   - Shows database host counts
   - Provides troubleshooting guidance

4. **fix_all_issues.sh** (Run on server)
   - General server-side fixes
   - Database initialization
   - File permissions
   - Service verification

### Documentation

- **docs/internal/PRODUCTION_HARDENING_RUNBOOK.md** - Complete guide for all fixes and deployment procedures
- **RELEASE_NOTES_2.0.1.md** - This file

## Installation

### Fresh Installation

```bash
# Extract package
tar -xzf patchmaster-2.0.1.tar.gz
cd patchmaster-2.0.1

# Run installation
sudo bash packaging/install-bare.sh
```

The installation will automatically:
- Generate secure random passwords
- Configure WebSocket support in nginx
- Initialize database with proper feedback
- Set up all services correctly

### Upgrade from 2.0.0

```bash
# Backup current installation
sudo systemctl stop patchmaster-backend
sudo cp -r /opt/patchmaster /opt/patchmaster.backup.$(date +%Y%m%d)

# Extract new version
tar -xzf patchmaster-2.0.1.tar.gz
cd patchmaster-2.0.1

# Run installation (will detect existing installation)
sudo bash packaging/install-bare.sh

# Run WebSocket fix
sudo bash fix_websocket_and_groups.sh

# Verify installation
sudo bash diagnose_agent_issues.sh
```

### Agent Installation/Update

```bash
# Download agent package from PatchMaster server
curl -fsSL -o agent-latest.deb http://YOUR_SERVER_IP:3000/download/agent-latest.deb

# Install agent
sudo dpkg -i agent-latest.deb || sudo apt-get install -f -y

# Run registration fix
sudo bash fix_agent_registration.sh
```

## Post-Installation Steps

### On Server:

1. Run diagnostics:
   ```bash
   sudo bash diagnose_agent_issues.sh
   ```

2. Verify services:
   ```bash
   systemctl status patchmaster-backend nginx postgresql
   ```

3. Test API endpoints:
   ```bash
   curl http://127.0.0.1:8000/api/health
   curl http://127.0.0.1:8000/api/groups/
   ```

### On Agents:

1. Verify services:
   ```bash
   systemctl status patch-agent patch-agent-heartbeat
   ```

2. Check logs:
   ```bash
   journalctl -u patch-agent -n 20
   journalctl -u patch-agent-heartbeat -n 20
   ```

### In Browser:

1. Clear browser cache (Ctrl+Shift+Delete)
2. Reload PatchMaster interface
3. Navigate to Groups & Tags page (should work now)
4. Verify hosts appear in Hosts page
5. Check browser console (F12) - should have no WebSocket errors

## Known Issues

None at this time. All reported issues from 2.0.0 have been fixed.

## Breaking Changes

None. This is a backward-compatible bug fix release.

## Files Modified

### Backend:
- `backend/database.py` - Database initialization feedback
- `backend/api/canary_testing.py` - Full rollout implementation
- `backend/api/register_v2.py` - Agent registration (improvements)
- `backend/api/groups.py` - Groups API (already correct)
- `backend/api/notifications.py` - WebSocket endpoint (already correct)

### Agent:
- `agent/agent.py` - Fixed bare exceptions (15 instances)
- `agent/solaris_manager.py` - Fixed bare exceptions
- `agent/aix_manager.py` - Fixed bare exceptions
- `agent/hpux_manager.py` - Fixed bare exceptions
- `agent/patchrepo_api.py` - Fixed bare exceptions

### Installation:
- `packaging/install-bare.sh` - WebSocket headers, secure passwords

### Vendor:
- `vendor/app.py` - Expanded weak password list

### New Files:
- `fix_websocket_and_groups.sh` - WebSocket and Groups fixes
- `fix_agent_registration.sh` - Agent registration fixes
- `diagnose_agent_issues.sh` - Comprehensive diagnostics
- `docs/internal/PRODUCTION_HARDENING_RUNBOOK.md` - Complete deployment guide
- `OFFLINE_AGENT_INSTALLATION.md` - Offline agent installation guide
- `agent/download-wheels.sh` - Download Python wheels for offline builds
- `RELEASE_NOTES_2.0.1.md` - This file

## Verification

Package integrity:
```bash
# Verify checksum
sha256sum -c patchmaster-2.0.1.tar.gz.sha256

# Expected output:
# patchmaster-2.0.1.tar.gz: OK
```

## Support & Troubleshooting

If you encounter issues:

1. **Read the documentation:**
   - `docs/internal/PRODUCTION_HARDENING_RUNBOOK.md` - Complete troubleshooting guide
   - `README.md` - General installation instructions

2. **Run diagnostics:**
   ```bash
   sudo bash diagnose_agent_issues.sh > diagnostics.txt
   ```

3. **Check logs:**
   ```bash
   # Backend logs
   journalctl -u patchmaster-backend -n 100

   # Agent logs
   journalctl -u patch-agent -n 50
   journalctl -u patch-agent-heartbeat -n 50

   # nginx logs
   tail -f /var/log/nginx/error.log
   ```

4. **Common solutions:**
   - WebSocket issues: Run `fix_websocket_and_groups.sh`
   - Agent not visible: Run `fix_agent_registration.sh` on agent
   - Groups page not working: Clear browser cache and reload
   - Database issues: Check PostgreSQL service and DATABASE_URL

## Upgrade Recommendations

**Priority:** HIGH - All users should upgrade

**Affected Users:**
- Anyone experiencing Groups & Tags page failures
- Anyone with agents not appearing in UI
- Anyone concerned about security (weak passwords, exception handling)
- Anyone using canary testing feature

**Downtime:** Minimal (< 5 minutes for backend restart)

## Testing

This release has been tested with:
- Fresh installations on Ubuntu 20.04, 22.04, 24.04
- Upgrades from PatchMaster 2.0.0
- Agent registration on Ubuntu, Debian, RHEL, CentOS
- WebSocket connections in Chrome, Firefox, Edge
- Groups & Tags page functionality
- Database initialization and upgrades

## Credits

All fixes developed and tested by the PatchMaster team.

Special thanks to users who reported these issues and provided detailed logs for debugging.

## Next Release

Version 2.0.2 is planned for May 2026 with additional features and improvements.

---

**Download:** `patchmaster-2.0.1.tar.gz` (74.7 MB)  
**Checksum:** See `patchmaster-2.0.1.tar.gz.sha256`  
**Git Tag:** v2.0.1  
**Build Date:** 2026-04-16
