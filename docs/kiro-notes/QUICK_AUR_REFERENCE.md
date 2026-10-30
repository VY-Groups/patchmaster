# Quick AUR Reference Guide

**For**: Arch Linux Users and Administrators  
**Status**: Production Ready ✅

---

## TL;DR

Patch-SecOps Solution now fully supports AUR packages via yay or paru. Install an AUR helper, and Patch-SecOps Solution handles the rest automatically.

---

## Quick Setup

```bash
# 1. Install prerequisites
sudo pacman -S --needed git base-devel

# 2. Install yay (recommended)
git clone https://aur.archlinux.org/yay.git
cd yay && makepkg -si

# 3. Done! Patch-SecOps Solution auto-detects yay
```

---

## Quick Usage

### Python API

```python
from agent import PacmanManager

pm = PacmanManager()

# Install anything (official or AUR)
pm.install(["vim", "yay", "google-chrome"])

# List all updates
updates = pm.list_upgradable()

# Refresh everything
pm.refresh()
```

### REST API

```bash
# Install packages
curl -X POST http://localhost:8080/execute/patch \
  -d '{"packages": ["vim", "yay", "google-chrome"]}'

# List updates
curl http://localhost:8080/packages/upgradable
```

---

## What Works

✅ Install official packages  
✅ Install AUR packages  
✅ Install mixed packages  
✅ List AUR updates  
✅ Remove AUR packages  
✅ Track package source  
✅ Auto-detect yay/paru  
✅ Graceful fallback if no helper  

---

## What's Different

### Before:
```python
pm.install(["yay"])  # ❌ Failed
```

### After:
```python
pm.install(["yay"])  # ✅ Works!
```

---

## Package Source Tracking

```python
installed = pm.list_installed()
# Returns:
[
  {"name": "vim", "version": "9.0", "source": "official"},
  {"name": "yay", "version": "12.0", "source": "aur"},
  {"name": "google-chrome", "version": "120.0", "source": "aur"}
]
```

---

## AUR Helpers Supported

| Helper | Priority | Status |
|--------|----------|--------|
| yay | 1st choice | ✅ Fully supported |
| paru | 2nd choice | ✅ Fully supported |
| None | Fallback | ✅ Official packages only |

---

## Common Operations

### Full System Upgrade

```python
# Get all updates
updates = pm.list_upgradable()
packages = [u['name'] for u in updates]

# Install all
pm.install(packages)
```

### Install AUR Package

```python
# Just use install() - it figures it out
pm.install(["google-chrome"])
```

### Check Package Source

```python
installed = pm.list_installed()
aur_packages = [p for p in installed if p['source'] == 'aur']
print(f"AUR packages: {len(aur_packages)}")
```

### Refresh Databases

```python
# Refreshes both official and AUR
pm.refresh()
```

---

## Troubleshooting

### No AUR Helper Found

```python
pm = PacmanManager()
if not pm.aur_helper:
    print("Install yay or paru first!")
```

### Package Not Found

```python
# Check if it's in AUR
if pm._is_aur_package("package-name"):
    print("It's an AUR package")
else:
    print("Not found or official")
```

### Build Failed

AUR packages compile from source. If build fails:
1. Check build dependencies
2. Review PKGBUILD
3. Check Arch Linux forums

---

## Best Practices

### 1. Always Use Snapshots

```python
# Before major updates
pm.install(packages, auto_snapshot=True)
```

### 2. Full System Upgrades

```python
# Don't do partial upgrades on Arch
all_updates = pm.list_upgradable()
pm.install([u['name'] for u in all_updates])
```

### 3. Review AUR Packages

```bash
# Before installing unknown AUR packages
yay -G package-name  # Download PKGBUILD
cat package-name/PKGBUILD  # Review it
```

### 4. Test in Staging

```bash
# Test updates in staging environment first
# Arch rolling release can have breaking changes
```

---

## Security Notes

⚠️ **AUR Packages Are Community-Maintained**

- Less vetted than official repos
- Review PKGBUILDs before installation
- Build scripts execute with user privileges
- Use trusted packages only

---

## Performance Notes

### Official Packages:
- ⚡ Fast (pre-compiled binaries)
- 📦 Downloaded from mirrors

### AUR Packages:
- 🔨 Slower (compile from source)
- 📝 Build time varies by package
- 💾 Requires disk space for build

---

## API Reference

### Methods

```python
pm = PacmanManager()

# Properties
pm.aur_helper  # "yay", "paru", or None

# Methods
pm.list_installed()  # List all packages
pm.list_upgradable()  # List updates
pm.refresh()  # Sync databases
pm.install(packages)  # Install packages
pm.remove(packages)  # Remove packages
pm.check_reboot()  # Check if reboot needed
pm.install_aur_helper()  # Helper install guide
pm._detect_aur_helper()  # Detect helper
pm._is_aur_package(pkg)  # Check if AUR
```

---

## Examples

### Example 1: Install Development Tools

```python
pm = PacmanManager()
pm.install([
    "base-devel",  # Official
    "yay",  # AUR
    "visual-studio-code-bin"  # AUR
])
```

### Example 2: Update All AUR Packages

```python
pm = PacmanManager()
updates = pm.list_upgradable()
aur_updates = [u['name'] for u in updates if u['source'] == 'aur']
pm.install(aur_updates)
```

### Example 3: Check System Status

```python
pm = PacmanManager()

print(f"AUR Helper: {pm.aur_helper}")

installed = pm.list_installed()
aur_count = len([p for p in installed if p['source'] == 'aur'])
print(f"AUR Packages: {aur_count}")

updates = pm.list_upgradable()
aur_updates = len([u for u in updates if u['source'] == 'aur'])
print(f"AUR Updates: {aur_updates}")
```

---

## FAQ

### Q: Do I need to install yay manually?
**A**: Yes, AUR helpers must be installed manually first.

### Q: Can I use paru instead of yay?
**A**: Yes, Patch-SecOps Solution detects both automatically.

### Q: What if I don't have an AUR helper?
**A**: Patch-SecOps Solution still works for official packages.

### Q: Are AUR packages safe?
**A**: They're community-maintained. Review PKGBUILDs first.

### Q: Why is AUR installation slower?
**A**: AUR packages compile from source.

### Q: Can I install official and AUR packages together?
**A**: Yes! Just pass them all to `install()`.

---

## Documentation

- [Full AUR Documentation](AUR_SUPPORT_COMPLETE.md)
- [Arch Linux Guide](../ARCH_LINUX_GUIDE.md)
- [Verification Report](AUR_IMPLEMENTATION_VERIFICATION.md)
- [Platform Matrix](PLATFORM_COMPATIBILITY_MATRIX.md)

---

## Support

For issues or questions:
1. Check [Arch Linux Guide](../ARCH_LINUX_GUIDE.md)
2. Review [AUR Documentation](AUR_SUPPORT_COMPLETE.md)
3. Check Arch Linux forums
4. Review AUR package comments

---

**Quick Reference Version**: 1.0  
**Last Updated**: April 6, 2026  
**Status**: Production Ready ✅
