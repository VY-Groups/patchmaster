# 🐧 Patch-SecOps Solution Arch Linux Deployment Guide

## 📋 Overview

Patch-SecOps Solution now fully supports Arch Linux and Arch-based distributions (Manjaro, EndeavourOS, Garuda, etc.) through the new PacmanManager implementation. This guide covers installation, configuration, and best practices for Arch Linux environments.

---

## ✅ Supported Distributions

| Distribution | Support Status | Package Manager | Notes |
|--------------|----------------|-----------------|-------|
| **Arch Linux** | ✅ Full | pacman | Official support |
| **Manjaro** | ✅ Full | pacman | Arch-based, auto-detected |
| **EndeavourOS** | ✅ Full | pacman | Arch-based, auto-detected |
| **Garuda Linux** | ✅ Full | pacman | Arch-based, should work |
| **ArcoLinux** | ✅ Full | pacman | Arch-based, should work |

---

## 🚀 Quick Start

### Prerequisites

```bash
# Update system
sudo pacman -Syu

# Install required dependencies
sudo pacman -S python python-pip postgresql nginx

# Optional: Install monitoring tools
sudo pacman -S prometheus grafana
```

### Agent Installation

#### Method 1: From Patch-SecOps Solution Controller

```bash
# Download and run the agent installer
curl -O http://your-patchmaster-server/static/install-agent.sh
chmod +x install-agent.sh
sudo ./install-agent.sh
```

#### Method 2: Manual Installation

```bash
# Clone or download the agent
git clone <repository-url>
cd patchmaster/agent

# Install Python dependencies
pip install -r requirements.txt

# Run the agent
sudo python agent.py
```

---

## 🔧 Configuration

### Agent Configuration

Create `/etc/patchmaster/agent.conf`:

```ini
[agent]
controller_url = https://your-patchmaster-server
agent_token = your-agent-token-here
port = 8080
metrics_port = 9100

[logging]
level = INFO
file = /var/log/patchmaster/agent.log

[snapshots]
directory = /var/lib/patchmaster/snapshots
max_snapshots = 10
```

### Systemd Service

Create `/etc/systemd/system/patchmaster-agent.service`:

```ini
[Unit]
Description=Patch-SecOps Solution Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/patchmaster/agent
ExecStart=/usr/bin/python /opt/patchmaster/agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable patchmaster-agent
sudo systemctl start patchmaster-agent
sudo systemctl status patchmaster-agent
```

---

## 📦 Package Management

### Supported Operations

| Operation | Command | Patch-SecOps Solution Support |
|-----------|---------|---------------------|
| List installed | `pacman -Q` | ✅ Yes |
| List upgradable | `pacman -Qu` | ✅ Yes |
| Refresh databases | `pacman -Sy` | ✅ Yes |
| Install packages | `pacman -S` | ✅ Yes |
| Install local | `pacman -U` | ✅ Yes |
| Remove packages | `pacman -R` | ✅ Yes |
| Check reboot | kernel version | ✅ Yes |

### Example API Calls

```bash
# List installed packages
curl http://localhost:8080/packages/installed

# List upgradable packages
curl http://localhost:8080/packages/upgradable

# Refresh package databases
curl -X POST http://localhost:8080/packages/refresh

# Install packages
curl -X POST http://localhost:8080/execute/patch \
  -H "Content-Type: application/json" \
  -d '{"packages": ["vim", "htop"]}'

# Remove packages
curl -X POST http://localhost:8080/software/manage \
  -H "Content-Type: application/json" \
  -d '{"action": "remove", "packages": ["vim"]}'
```

---

## 📸 Snapshot & Rollback

### Snapshot Strategies

Patch-SecOps Solution supports multiple snapshot strategies on Arch Linux:

#### 1. Package List Snapshot (Default)

Saves a list of installed packages and their versions.

```bash
# Create snapshot
curl -X POST http://localhost:8080/snapshot/create \
  -H "Content-Type: application/json" \
  -d '{"name": "before-update", "mode": "packages"}'

# Restore snapshot
curl -X POST http://localhost:8080/snapshot/rollback \
  -H "Content-Type: application/json" \
  -d '{"name": "before-update"}'
```

**What's Saved**:
- All installed packages (`pacman -Q`)
- Explicitly installed packages (`pacman -Qqe`)
- Package versions
- Pacman configuration (`/etc/pacman.conf`)
- Mirror list (`/etc/pacman.d/mirrorlist`)

#### 2. Btrfs Snapshot (If Available)

If your root filesystem is Btrfs, Patch-SecOps Solution can create filesystem snapshots.

```bash
# Check if Btrfs is available
findmnt -n -o FSTYPE /

# Create Btrfs snapshot
curl -X POST http://localhost:8080/snapshot/create \
  -H "Content-Type: application/json" \
  -d '{"name": "before-update", "mode": "full_system"}'
```

**Requirements**:
- Root filesystem must be Btrfs
- Sufficient disk space
- Btrfs tools installed (`pacman -S btrfs-progs`)

#### 3. LVM Snapshot (If Available)

If your root filesystem is on LVM, standard LVM snapshots work.

```bash
# Check if LVM is available
lvdisplay

# Create LVM snapshot (handled automatically)
curl -X POST http://localhost:8080/snapshot/create \
  -H "Content-Type: application/json" \
  -d '{"name": "before-update", "mode": "full_system"}'
```

---

## 🔄 Reboot Detection

Patch-SecOps Solution automatically detects when a reboot is required on Arch Linux by:

1. Comparing running kernel version with installed kernel version
2. Checking if systemd needs restart
3. Detecting critical package updates

```bash
# Check if reboot is required
curl http://localhost:8080/status

# Response includes:
{
  "reboot_required": true,
  "reason": "kernel_updated"
}
```

### Kernel Packages Detected

- `linux` (default kernel)
- `linux-lts` (long-term support)
- `linux-zen` (optimized)
- `linux-hardened` (security-focused)

---

## 🌐 Cloud Deployment

### DigitalOcean

```bash
# Create Arch Linux droplet
doctl compute droplet create patchmaster-arch \
  --image arch-linux \
  --size s-1vcpu-1gb \
  --region nyc1

# SSH and install agent
ssh root@<droplet-ip>
curl -O http://your-patchmaster-server/static/install-agent.sh
chmod +x install-agent.sh
sudo ./install-agent.sh
```

### Linode

```bash
# Create Arch Linux instance
linode-cli linodes create \
  --image linode/arch \
  --region us-east \
  --type g6-nanode-1

# SSH and install agent
ssh root@<instance-ip>
curl -O http://your-patchmaster-server/static/install-agent.sh
chmod +x install-agent.sh
sudo ./install-agent.sh
```

### AWS (Community AMI)

```bash
# Find Arch Linux AMI
aws ec2 describe-images \
  --owners 093273469852 \
  --filters "Name=name,Values=arch-linux-*"

# Launch instance
aws ec2 run-instances \
  --image-id ami-xxxxxxxxx \
  --instance-type t2.micro \
  --key-name your-key

# SSH and install agent
ssh arch@<instance-ip>
curl -O http://your-patchmaster-server/static/install-agent.sh
chmod +x install-agent.sh
sudo ./install-agent.sh
```

---

## ⚠️ Important Notes

### AUR (Arch User Repository)

✅ **FULLY SUPPORTED** - Patch-SecOps Solution now has complete AUR support via yay or paru!

**Features**:
- Automatic detection of yay or paru AUR helpers
- Install both official and AUR packages in one operation
- List and update AUR packages
- Track package source (official vs AUR)

**Setup**: Install an AUR helper first:

```bash
# Install yay (recommended)
sudo pacman -S --needed git base-devel
git clone https://aur.archlinux.org/yay.git
cd yay && makepkg -si

# Or install paru (alternative)
git clone https://aur.archlinux.org/paru.git
cd paru && makepkg -si
```

**Usage**:

```bash
# Patch-SecOps Solution automatically detects and uses your AUR helper
# Install mixed packages (official + AUR)
curl -X POST http://localhost:8080/execute/patch \
  -H "Content-Type: application/json" \
  -d '{
    "packages": ["vim", "yay", "google-chrome"],
    "auto_snapshot": true
  }'

# List all updates (includes AUR)
curl http://localhost:8080/packages/upgradable
```

### Rolling Release Model

Arch Linux uses a rolling release model, which means:

- No concept of "security-only" updates
- All packages are always latest version
- More frequent updates than stable distributions
- Higher risk of breaking changes
- AUR packages also follow rolling release

**Recommendation**: Test updates in a staging environment first. Always perform full system upgrades:

```bash
# Full system upgrade (official + AUR)
curl -X POST http://localhost:8080/execute/patch \
  -H "Content-Type: application/json" \
  -d '{
    "upgrade_all": true,
    "auto_snapshot": true
  }'
```

### Kernel Updates

Kernel updates on Arch require a reboot. Patch-SecOps Solution will:

1. Detect kernel updates
2. Mark system as "reboot required"
3. Optionally schedule automatic reboot

```bash
# Configure automatic reboot after kernel updates
curl -X POST http://localhost:8080/execute/patch \
  -H "Content-Type: application/json" \
  -d '{
    "packages": ["linux"],
    "auto_reboot": true,
    "auto_snapshot": true
  }'
```

---

## 🧪 Testing

### Verify Installation

```bash
# Check agent status
sudo systemctl status patchmaster-agent

# Check agent logs
sudo journalctl -u patchmaster-agent -f

# Test API endpoint
curl http://localhost:8080/health

# Expected response:
{
  "status": "healthy",
  "os": "Linux",
  "package_manager": "pacman",
  "version": "2.0.0"
}
```

### Test Package Operations

```bash
# List installed packages
curl http://localhost:8080/packages/installed | jq

# List upgradable packages
curl http://localhost:8080/packages/upgradable | jq

# Refresh databases
curl -X POST http://localhost:8080/packages/refresh

# Install a test package
curl -X POST http://localhost:8080/execute/patch \
  -H "Content-Type: application/json" \
  -d '{"packages": ["htop"], "dry_run": true}'
```

### Test Snapshot Operations

```bash
# Create test snapshot
curl -X POST http://localhost:8080/snapshot/create \
  -H "Content-Type: application/json" \
  -d '{"name": "test-snapshot", "mode": "packages"}'

# List snapshots
curl http://localhost:8080/snapshot/list | jq

# Delete test snapshot
curl -X DELETE http://localhost:8080/snapshot/delete/test-snapshot
```

---

## 🔧 Troubleshooting

### Agent Won't Start

```bash
# Check logs
sudo journalctl -u patchmaster-agent -n 50

# Common issues:
# 1. Python dependencies missing
pip install -r /opt/patchmaster/agent/requirements.txt

# 2. Port already in use
sudo netstat -tulpn | grep 8080

# 3. Permissions issue
sudo chown -R root:root /opt/patchmaster
```

### Package Operations Fail

```bash
# Check pacman database
sudo pacman -Sy

# Verify pacman is working
sudo pacman -Q | head

# Check for lock file
sudo rm /var/lib/pacman/db.lck

# Refresh keyring
sudo pacman -Sy archlinux-keyring
```

### Snapshot Creation Fails

```bash
# Check disk space
df -h

# Check snapshot directory
ls -la /var/lib/patchmaster/snapshots

# Check permissions
sudo chown -R root:root /var/lib/patchmaster

# For Btrfs snapshots
sudo btrfs filesystem show
sudo btrfs subvolume list /
```

### Reboot Detection Not Working

```bash
# Manually check kernel versions
uname -r
pacman -Q linux

# Check systemd status
systemctl is-system-running

# Force reboot check
curl http://localhost:8080/status | jq '.reboot_required'
```

---

## 📊 Performance Tuning

### Pacman Configuration

Edit `/etc/pacman.conf`:

```ini
# Enable parallel downloads
ParallelDownloads = 5

# Use faster mirrors
Include = /etc/pacman.d/mirrorlist

# Enable color output
Color

# Verbose package lists
VerbosePkgLists
```

### Mirror Optimization

```bash
# Install reflector
sudo pacman -S reflector

# Update mirrorlist with fastest mirrors
sudo reflector --latest 20 --protocol https --sort rate \
  --save /etc/pacman.d/mirrorlist

# Refresh databases
sudo pacman -Sy
```

### Agent Performance

```bash
# Increase agent timeout for large updates
export PM_AGENT_TIMEOUT=7200

# Enable caching
export PM_CACHE_ENABLED=1
export PM_CACHE_DIR=/var/cache/patchmaster
```

---

## 🔒 Security Best Practices

### 1. Use HTTPS

```bash
# Configure agent to use HTTPS
sed -i 's|http://|https://|g' /etc/patchmaster/agent.conf
```

### 2. Restrict Agent Access

```bash
# Create dedicated user
sudo useradd -r -s /bin/false patchmaster

# Update service file
sudo sed -i 's|User=root|User=patchmaster|g' \
  /etc/systemd/system/patchmaster-agent.service

# Grant sudo permissions for pacman only
echo "patchmaster ALL=(ALL) NOPASSWD: /usr/bin/pacman" | \
  sudo tee /etc/sudoers.d/patchmaster
```

### 3. Enable Firewall

```bash
# Install and configure firewall
sudo pacman -S ufw
sudo ufw allow 8080/tcp
sudo ufw allow 9100/tcp
sudo ufw enable
```

### 4. Regular Security Updates

```bash
# Schedule automatic security updates
sudo systemctl enable --now patchmaster-agent
```

---

## 📚 Additional Resources

- [Arch Linux Wiki](https://wiki.archlinux.org/)
- [Pacman Documentation](https://wiki.archlinux.org/title/Pacman)
- [Btrfs Snapshots](https://wiki.archlinux.org/title/Btrfs#Snapshots)
- [Patch-SecOps Solution Documentation](../README.md)

---

## 🆘 Support

For issues specific to Arch Linux:

1. Check the [GitHub Issues](https://github.com/your-repo/issues) with label `arch-linux`
2. Review the [Troubleshooting](#troubleshooting) section
3. Contact support with:
   - Arch Linux version (`cat /etc/os-release`)
   - Kernel version (`uname -r`)
   - Agent logs (`journalctl -u patchmaster-agent`)
   - Error messages

---

**Status**: ✅ Production Ready  
**Last Updated**: 2026-04-06  
**Version**: 2.0.0+arch
