# Patch-SecOps Solution Release Notes - Version 2.0.7

**Release Date:** April 12, 2026  
**Package Size:** 123 MB  
**Checksum:** `beb44f1a8debc73af6da588f6d82ae19b2fc113288e5e3eba46ac8ce1c2507e9`

## What's New in 2.0.7

### License Warning Manual Dismiss
- License expiration warning banner now has a manual close button (×)
- User can dismiss the warning at any time
- Warning only shows when license has 30 days or less remaining
- Clicking the warning text navigates to License page
- Clicking the × button dismisses the warning

### Previous Features (from 2.0.6)

#### FreeBSD Support (Bundled Agent)
- FreeBSD agent includes bundled Python virtual environment (2.5 MB)
- No manual dependency installation required
- Air-gapped installation ready

#### Agent Package Sizes
All agents include bundled Python dependencies:
- **Windows:** 48 MB (includes Python runtime)
- **Alpine Linux:** 4.5 MB
- **Arch Linux:** 3.1 MB
- **Debian/Ubuntu:** 3.0 MB
- **FreeBSD:** 2.5 MB (bundled)
- **RHEL/RPM:** 1.3 MB

#### Dark Mode
- Full dark mode support with theme toggle
- User preference persists across sessions
- Smooth transitions between light and dark themes

#### Bug Fixes
- Fixed array validation errors in CVE Tracker, Jobs, and Audit pages
- Fixed white page issue after reinstall
- Improved text visibility in dark mode

## Installation

### Extract Package
```bash
tar -xzf patchmaster-2.0.7.tar.gz
cd patchmaster-2.0.7
```

### Verify Checksum
```bash
sha256sum -c patchmaster-2.0.7.tar.gz.sha256
```

### Deploy
```bash
# Using Docker Compose (recommended)
docker-compose -f docker-compose.prod.yml up -d

# Or using auto-setup script
./auto-setup.sh
```

## Upgrade from 2.0.6

1. **Backup your data** (database, configuration files)
2. **Stop existing services**
   ```bash
   docker-compose down
   ```
3. **Extract new package** over existing installation
4. **Start services**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

## User Interface Changes

### License Warning Banner
The license expiration warning banner now includes:
- **Close button (×):** Manually dismiss the warning
- **Click text:** Navigate to License page to manage license
- **Visibility:** Only shows when ≤30 days remaining
- **Persistence:** Warning reappears on next login if still within 30 days

**Example:**
```
┌─────────────────────────────────────────────────────────────┐
│ License expires in 25 days (2026-05-07). Click here to... × │
└─────────────────────────────────────────────────────────────┘
```

## Technical Details

### Frontend Changes
- `frontend/src/App.js`: 
  - Removed auto-dismiss timer (15 seconds)
  - Added manual close button with × symbol
  - Updated banner layout to flexbox with close button
  - Close button stops event propagation to prevent navigation
- Build time: 4.87s

### Backend Changes
- No backend changes in this release

## Known Issues

None reported in this release.

## Support

For issues or questions:
- Email: support@VYGROUP.com
- Documentation: See `docs/` directory in package

## Version History

- **2.0.7** (Apr 12, 2026): Manual dismiss for license warning
- **2.0.6** (Apr 12, 2026): Auto-dismiss license warning, bundled FreeBSD agent
- **2.0.0** (Apr 8, 2026): Initial release with dark mode and UI redesign
