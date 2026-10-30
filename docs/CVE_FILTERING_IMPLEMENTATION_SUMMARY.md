# CVE-Based Security Filtering - Implementation Summary

**Date**: April 12, 2026  
**Feature**: Universal Security-Only Updates for All Platforms  
**Status**: ✅ Implemented

---

## What Was Implemented

### 1. Backend API Endpoint ✅

**File**: `backend/api/cve.py`

**New Endpoint**: `POST /api/cve/filter-security`

**Purpose**: Filter a list of packages to only those with security vulnerabilities

**Features**:
- Accepts list of packages and host ID
- Queries CVE database for vulnerabilities
- Filters by severity threshold (low, medium, high, critical)
- Returns security-critical packages with CVE details
- Maps OS to family for accurate CVE lookup

**Request Example**:
```json
{
  "host_id": "abc123",
  "packages": ["vim", "curl", "nginx", "firefox"],
  "severity_threshold": "medium"
}
```

**Response Example**:
```json
{
  "security_packages": ["vim", "curl"],
  "cve_details": {
    "vim": [
      {
        "cve_id": "CVE-2024-1234",
        "severity": "critical",
        "score": 9.8,
        "description": "Buffer overflow in vim"
      }
    ],
    "curl": [
      {
        "cve_id": "CVE-2024-5678",
        "severity": "high",
        "score": 7.5,
        "description": "TLS certificate validation bypass"
      }
    ]
  },
  "filtered_count": 2,
  "total_count": 4,
  "os_family": "arch",
  "severity_threshold": "medium"
}
```

---

### 2. Agent Base Class Helper Methods ✅

**File**: `agent/agent.py`

**Added to BasePackageManager**:

#### `_filter_security_packages(packages)`
- Queries backend CVE filter API
- Extracts package names from list
- Handles authentication with bearer token
- Returns filtered list of security packages
- Graceful fallback: returns all packages if query fails

#### `_get_host_id()`
- Reads host ID from local cache
- Tries multiple locations: `/var/lib/patch-agent/host_id`, `/etc/patch-agent/host_id`, `host_id`
- Returns None if not found

**Features**:
- Automatic retry logic
- Timeout handling (30 seconds)
- Logging for debugging
- Fallback to full upgrade if CVE query fails

---

### 3. Platform-Specific Implementations ✅

#### Arch Linux (PacmanManager)

**File**: `agent/agent.py` (lines ~685-750)

**Changes**:
```python
def install(self, packages, local=False, security_only=False, ...):
    # NEW: Security-only filtering via backend CVE database
    if security_only and not local and not packages:
        upgradable = self.list_upgradable()
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        packages = security_pkgs
    
    # Rest of existing implementation...
```

**Result**: ✅ Arch Linux now supports security-only updates via CVE filtering

---

#### Alpine Linux (ApkManager)

**File**: `agent/agent.py` (lines ~1100-1140)

**Changes**:
```python
def install(self, packages, local=False, security_only=False, ...):
    # NEW: Security-only filtering via backend CVE database
    if security_only and not local and not packages:
        upgradable = self.list_upgradable()
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        packages = security_pkgs
    
    # Rest of existing implementation...
```

**Result**: ✅ Alpine now supports security-only updates via CVE filtering

---

#### FreeBSD (FreeBSDPkgManager)

**File**: `agent/agent.py` (lines ~1220-1260)

**Changes**:
```python
def install(self, packages, local=False, security_only=False, ...):
    # NEW: Security-only filtering via backend CVE database
    if security_only and not local and not packages:
        upgradable = self.list_upgradable()
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        packages = security_pkgs
    
    # Rest of existing implementation...
```

**Result**: ✅ FreeBSD now supports security-only updates via CVE filtering

---

### 4. Documentation Updates ✅

**File**: `docs/AGENT_CAPABILITIES_MATRIX.md`

**Changes**:
1. Updated capability table to show ✅ for security-only updates on Arch, Alpine, FreeBSD
2. Added "via CVE filtering" notes for these platforms
3. Added comprehensive "CVE-Based Security Filtering" section explaining:
   - How it works
   - Implementation details
   - Platform support matrix
   - Benefits
   - CVE data sources

**Before**:
```
| Arch Linux | ❌ N/A |
| Alpine | ❌ N/A |
| FreeBSD | ❌ N/A |
```

**After**:
```
| Arch Linux | ✅ via CVE filtering |
| Alpine | ✅ via CVE filtering |
| FreeBSD | ✅ via CVE filtering |
```

---

## How It Works

### User Flow

1. **User Action**: Clicks "Install Security Updates Only" in Patch-SecOps Solution UI
2. **Backend Request**: Sends patch request with `security_only=true`
3. **Agent Processing**:
   - Gets list of upgradable packages
   - Queries backend: `POST /api/cve/filter-security`
   - Receives filtered list of security packages
   - Installs only those packages
4. **Result**: Only security-critical packages are installed

### Technical Flow

```
┌─────────────────────────────────────────────────────────────┐
│ User: "Install Security Updates Only"                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Agent: Get upgradable packages                              │
│ Result: vim, curl, nginx, firefox                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Agent → Backend: POST /api/cve/filter-security             │
│ Body: {"host_id": "abc123", "packages": [...]}            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Backend: Query CVE database                                 │
│ - vim: CVE-2024-1234 (Critical) → SECURITY                 │
│ - curl: CVE-2024-5678 (High) → SECURITY                    │
│ - nginx: No CVEs → NOT SECURITY                            │
│ - firefox: No CVEs → NOT SECURITY                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Backend → Agent: {"security_packages": ["vim", "curl"]}   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Agent: Install only vim and curl                           │
│ Command: pacman -S vim curl                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Benefits

### ✅ Universal Security-Only Updates
- Works on ALL platforms (Debian, RHEL, Arch, Alpine, FreeBSD, Windows)
- Consistent user experience across all OS types
- No platform limitations

### ✅ CVE-Driven Intelligence
- Uses actual vulnerability data, not just package manager flags
- Can filter by severity (critical, high, medium, low)
- Provides CVE details to users

### ✅ Backward Compatible
- Platforms with native support continue using native methods
- CVE-based filtering only used on platforms without native support
- Fallback to full upgrade if CVE query fails

### ✅ Centralized CVE Management
- Single source of truth for vulnerability data
- Backend maintains CVE database
- Agents don't need local CVE databases

---

## Testing

### Manual Testing Steps

1. **Setup**: Deploy agent on Arch/Alpine/FreeBSD host
2. **Verify**: Check agent can communicate with backend
3. **Trigger**: Click "Install Security Updates Only" in UI
4. **Observe**: Agent should query CVE API and install only security packages
5. **Validate**: Check only packages with CVEs were installed

### Expected Behavior

**Scenario 1: Security updates available**
- Agent queries backend
- Backend returns filtered list
- Agent installs only security packages
- Result: "Installed 2 security updates (vim, curl)"

**Scenario 2: No security updates**
- Agent queries backend
- Backend returns empty list
- Agent skips installation
- Result: "No security updates available"

**Scenario 3: Backend unavailable**
- Agent queries backend
- Query fails/times out
- Agent falls back to full upgrade
- Result: "CVE filter failed, installing all updates"

---

## Security Considerations

### 1. Authentication
- Agent uses bearer token for CVE API requests
- Token stored in environment variable `AGENT_TOKEN`
- Backend validates token before processing

### 2. Fallback Behavior
- If CVE query fails, agent installs ALL packages
- This is safer than skipping updates entirely
- Logged for monitoring and alerting

### 3. CVE Data Integrity
- CVE database must be regularly updated
- Use `/api/cve/sync` endpoint to sync from NVD
- Verify CVE data sources are authentic

---

## Performance

### CVE Query Performance
- **Timeout**: 30 seconds
- **Caching**: Backend can cache results for 5 minutes
- **Batch Processing**: Single query for all packages

### Agent Impact
- **Minimal overhead**: Single HTTP request per patch operation
- **Non-blocking**: Doesn't delay patch operations
- **Graceful degradation**: Falls back if query fails

---

## Monitoring

### Backend Metrics (to be added)
- `cve_filter_requests_total` - Total CVE filter requests
- `cve_filter_duration_seconds` - CVE query duration
- `cve_filter_packages_filtered` - Packages filtered per request

### Agent Logs
- `INFO: CVE filter: 2/4 packages have security issues`
- `WARNING: CVE filter failed with status 500, installing all packages`
- `WARNING: CVE filter error: timeout, installing all packages`

---

## Future Enhancements

### 1. Local CVE Cache
- Agent caches CVE data locally
- Reduces backend queries
- Works offline

### 2. CVE Severity Policies
- Admin sets minimum severity threshold
- Per-host or per-group policies
- Automatic security patching based on severity

### 3. CVE Notifications
- Alert users when critical CVEs affect their systems
- Email/Slack notifications for new CVEs
- CVE dashboard in UI

---

## Conclusion

**CVE-based security filtering is now fully implemented** across all platforms. This eliminates the "❌ N/A" limitations for Arch Linux, Alpine, and FreeBSD, providing a superior security patching experience across the entire infrastructure.

### Summary of Changes

| Component | Status | Files Modified |
|-----------|--------|----------------|
| Backend API | ✅ Complete | `backend/api/cve.py` |
| Agent Base Class | ✅ Complete | `agent/agent.py` (BasePackageManager) |
| Arch Linux Support | ✅ Complete | `agent/agent.py` (PacmanManager) |
| Alpine Support | ✅ Complete | `agent/agent.py` (ApkManager) |
| FreeBSD Support | ✅ Complete | `agent/agent.py` (FreeBSDPkgManager) |
| Documentation | ✅ Complete | `docs/AGENT_CAPABILITIES_MATRIX.md` |

### Result

**All platforms now support security-only updates!**

- ✅ Debian/Ubuntu: Native support
- ✅ RHEL/RPM: Native support
- ✅ openSUSE: Native support
- ✅ Windows: Native support
- ✅ **Arch Linux: CVE filtering** (NEW!)
- ✅ **Alpine: CVE filtering** (NEW!)
- ✅ **FreeBSD: CVE filtering** (NEW!)

---

**Implementation Date**: April 12, 2026  
**Version**: 2.0.8 (to be released)  
**Status**: Ready for testing and deployment
