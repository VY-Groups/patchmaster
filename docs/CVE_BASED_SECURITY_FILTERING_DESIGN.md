# CVE-Based Security Filtering - Technical Design

**Feature**: Universal Security-Only Updates for All Platforms  
**Date**: April 12, 2026  
**Status**: Design Phase

---

## Problem Statement

Currently, security-only updates work on platforms with native support (Debian, RHEL, openSUSE, Windows) but not on platforms without security classification (Arch Linux, Alpine, FreeBSD).

**Current Limitations**:
- ❌ Arch Linux: No security classification in pacman
- ❌ Alpine: No security classification in apk
- ❌ FreeBSD: No security classification in pkg

**Goal**: Enable security-only updates on ALL platforms using Patch-SecOps Solution's CVE database.

---

## Solution Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User clicks "Install Security Updates Only"             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Agent gets list of upgradable packages                  │
│    Example: vim, curl, nginx, firefox                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Agent queries Backend CVE API:                          │
│    POST /api/cve/filter-security                           │
│    Body: {                                                  │
│      "host_id": "abc123",                                   │
│      "packages": ["vim", "curl", "nginx", "firefox"]       │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Backend checks CVE database:                            │
│    - vim: CVE-2024-1234 (Critical)     → SECURITY          │
│    - curl: CVE-2024-5678 (High)        → SECURITY          │
│    - nginx: No CVEs                    → NOT SECURITY      │
│    - firefox: No CVEs                  → NOT SECURITY      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Backend returns filtered list:                          │
│    Response: {                                              │
│      "security_packages": ["vim", "curl"],                 │
│      "cve_details": {                                       │
│        "vim": ["CVE-2024-1234"],                           │
│        "curl": ["CVE-2024-5678"]                           │
│      }                                                      │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Agent installs ONLY security packages:                  │
│    pacman -S vim curl                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Details

### 1. Backend API Endpoint

**New Endpoint**: `POST /api/cve/filter-security`

**Purpose**: Filter a list of packages to only those with security vulnerabilities

**Request**:
```json
{
  "host_id": "abc123",
  "packages": ["vim", "curl", "nginx", "firefox"],
  "severity_threshold": "medium"  // optional: low, medium, high, critical
}
```

**Response**:
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
  "total_count": 4
}
```

**Implementation** (`backend/api/cve.py`):
```python
@router.post("/filter-security")
async def filter_security_packages(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Filter packages to only those with security vulnerabilities.
    Used by agents on platforms without native security classification.
    """
    host_id = body.get("host_id")
    packages = body.get("packages", [])
    severity_threshold = body.get("severity_threshold", "low")
    
    if not host_id or not packages:
        raise HTTPException(400, "host_id and packages required")
    
    # Get host to determine OS
    host = db.query(Host).filter(Host.id == host_id).first()
    if not host:
        raise HTTPException(404, "Host not found")
    
    # Query CVE database for each package
    security_packages = []
    cve_details = {}
    
    severity_scores = {
        "low": 0.1,
        "medium": 4.0,
        "high": 7.0,
        "critical": 9.0
    }
    min_score = severity_scores.get(severity_threshold, 0.1)
    
    for pkg in packages:
        # Query CVEs for this package on this OS
        cves = db.query(CVE).filter(
            CVE.package_name == pkg,
            CVE.os_family == host.os_family,
            CVE.cvss_score >= min_score
        ).all()
        
        if cves:
            security_packages.append(pkg)
            cve_details[pkg] = [
                {
                    "cve_id": cve.cve_id,
                    "severity": cve.severity,
                    "score": cve.cvss_score,
                    "description": cve.description
                }
                for cve in cves
            ]
    
    return {
        "security_packages": security_packages,
        "cve_details": cve_details,
        "filtered_count": len(security_packages),
        "total_count": len(packages)
    }
```

---

### 2. Agent Implementation

**Update Package Managers** (`agent/agent.py`):

#### Arch Linux (PacmanManager)

```python
def install(self, packages, local=False, security_only=False, 
            exclude_kernel=False, extra_flags=None):
    """Install packages (supports both official repos and AUR)"""
    
    # NEW: Security-only filtering via backend
    if security_only and not local and not packages:
        # Get all upgradable packages
        upgradable = self.list_upgradable()
        if not upgradable:
            return 0, "No upgradable packages"
        
        # Query backend for security packages
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        
        packages = security_pkgs
    
    # Rest of existing implementation...
    if not packages:
        return 0, "No packages specified"
    
    # Filter kernel packages if requested
    if exclude_kernel:
        packages = [p for p in packages if not p.startswith("linux")]
    
    # ... existing code continues ...
```

**Add Helper Method**:
```python
def _filter_security_packages(self, packages):
    """
    Query backend to filter packages to only those with CVEs.
    Used on platforms without native security classification.
    """
    try:
        import requests
        
        # Get controller URL and token from environment
        controller_url = os.getenv("CONTROLLER_URL", "http://localhost:3000")
        token = os.getenv("AGENT_TOKEN", "")
        
        # Get host ID from registration
        host_id = self._get_host_id()
        
        # Query backend
        response = requests.post(
            f"{controller_url}/api/cve/filter-security",
            json={
                "host_id": host_id,
                "packages": [p["name"] for p in packages],
                "severity_threshold": "medium"
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("security_packages", [])
        else:
            # Fallback: install all packages if backend query fails
            logging.warning(f"CVE filter failed: {response.status_code}")
            return [p["name"] for p in packages]
    
    except Exception as e:
        # Fallback: install all packages if query fails
        logging.warning(f"CVE filter error: {e}")
        return [p["name"] for p in packages]

def _get_host_id(self):
    """Get host ID from local cache or registration"""
    try:
        with open("/var/lib/patch-agent/host_id", "r") as f:
            return f.read().strip()
    except:
        return None
```

#### Alpine Linux (AlpineManager)

```python
def install(self, packages, local=False, security_only=False, 
            exclude_kernel=False, extra_flags=None):
    """Install packages"""
    
    # NEW: Security-only filtering via backend
    if security_only and not local and not packages:
        upgradable = self.list_upgradable()
        if not upgradable:
            return 0, "No upgradable packages"
        
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        
        packages = security_pkgs
    
    # Rest of existing implementation...
```

#### FreeBSD (FreeBSDPkgManager)

```python
def install(self, packages, local=False, security_only=False, 
            exclude_kernel=False, extra_flags=None):
    """Install packages"""
    
    # NEW: Security-only filtering via backend
    if security_only and not local and not packages:
        upgradable = self.list_upgradable()
        if not upgradable:
            return 0, "No upgradable packages"
        
        security_pkgs = self._filter_security_packages(upgradable)
        if not security_pkgs:
            return 0, "No security updates available"
        
        packages = security_pkgs
    
    # Rest of existing implementation...
```

---

### 3. CVE Database Requirements

**Existing Tables** (already in database):
```sql
CREATE TABLE cves (
    id SERIAL PRIMARY KEY,
    cve_id VARCHAR(20) NOT NULL,
    package_name VARCHAR(255) NOT NULL,
    os_family VARCHAR(50),  -- debian, rhel, arch, alpine, freebsd, windows
    severity VARCHAR(20),   -- low, medium, high, critical
    cvss_score FLOAT,
    description TEXT,
    published_date TIMESTAMP,
    fixed_version VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cves_package ON cves(package_name, os_family);
CREATE INDEX idx_cves_severity ON cves(severity, cvss_score);
```

**CVE Data Sources**:
- **Arch Linux**: https://security.archlinux.org/json
- **Alpine**: https://secdb.alpinelinux.org/
- **FreeBSD**: https://www.freebsd.org/security/advisories.html

---

### 4. Frontend Changes

**No changes required** - existing UI already has "Security Updates Only" checkbox that passes `security_only=true` to backend.

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
- Platforms with native support (Debian, RHEL, openSUSE) continue using native methods
- New CVE-based filtering only used on platforms without native support
- Fallback to full upgrade if CVE query fails

### ✅ Centralized CVE Management
- Single source of truth for vulnerability data
- Backend maintains CVE database
- Agents don't need local CVE databases

---

## Implementation Plan

### Phase 1: Backend API (2-3 hours)
1. Create `/api/cve/filter-security` endpoint
2. Implement CVE database query logic
3. Add severity filtering
4. Test with sample data

### Phase 2: Agent Implementation (3-4 hours)
1. Add `_filter_security_packages()` helper method to BasePackageManager
2. Update Arch Linux PacmanManager
3. Update Alpine AlpineManager
4. Update FreeBSD FreeBSDPkgManager
5. Test on each platform

### Phase 3: CVE Data Integration (4-6 hours)
1. Create CVE sync scripts for Arch, Alpine, FreeBSD
2. Schedule periodic CVE database updates
3. Verify CVE data accuracy

### Phase 4: Testing (2-3 hours)
1. Unit tests for CVE filtering
2. Integration tests on each platform
3. End-to-end testing with real CVE data

### Phase 5: Documentation (1-2 hours)
1. Update capabilities matrix
2. Update user documentation
3. Add CVE filtering examples

**Total Estimated Time**: 12-18 hours

---

## Testing Strategy

### Unit Tests
```python
def test_filter_security_packages_arch():
    """Test CVE-based filtering on Arch Linux"""
    packages = ["vim", "curl", "nginx"]
    # Mock CVE database with vim and curl having CVEs
    security_pkgs = filter_security_packages(packages)
    assert "vim" in security_pkgs
    assert "curl" in security_pkgs
    assert "nginx" not in security_pkgs
```

### Integration Tests
1. **Arch Linux**: Install security updates only, verify only CVE-affected packages installed
2. **Alpine**: Same test
3. **FreeBSD**: Same test
4. **Fallback**: Test with backend unavailable, verify full upgrade happens

---

## Security Considerations

### 1. CVE Data Integrity
- CVE database must be regularly updated
- Verify CVE data sources are authentic
- Handle stale CVE data gracefully

### 2. Agent-Backend Communication
- Use HTTPS for CVE queries
- Authenticate agent requests with tokens
- Rate limit CVE filter endpoint

### 3. Fallback Behavior
- If CVE query fails, default to full upgrade (safer than no upgrade)
- Log CVE query failures for monitoring
- Alert admins if CVE database is stale

---

## Performance Considerations

### 1. CVE Query Optimization
- Index CVE table by package_name and os_family
- Cache CVE query results for 5 minutes
- Batch CVE queries when possible

### 2. Agent Timeout
- Set 30-second timeout for CVE queries
- Don't block patch operations on slow CVE queries
- Use async requests where possible

---

## Monitoring & Metrics

### Backend Metrics
- `cve_filter_requests_total` - Total CVE filter requests
- `cve_filter_duration_seconds` - CVE query duration
- `cve_filter_packages_filtered` - Packages filtered per request
- `cve_database_age_hours` - Age of CVE data

### Agent Metrics
- `security_only_patches_total` - Security-only patch operations
- `cve_query_failures_total` - Failed CVE queries
- `security_packages_installed` - Packages installed via security filter

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

This design enables **universal security-only updates** across all platforms by leveraging Patch-SecOps Solution's CVE database. Platforms without native security classification (Arch, Alpine, FreeBSD) will query the backend to filter packages based on actual vulnerability data.

**Key Advantages**:
- ✅ Works on ALL platforms
- ✅ CVE-driven intelligence
- ✅ Backward compatible
- ✅ Centralized management
- ✅ Severity filtering
- ✅ Graceful fallback

This eliminates the "❌ N/A" limitations and provides a superior security patching experience across the entire infrastructure.
