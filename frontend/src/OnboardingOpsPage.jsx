import React, { useEffect, useMemo, useState } from 'react';
import './OpsPages.css';
import { API } from './appRuntime';

export default function OnboardingOpsPage({ AppIcon }) {
  const [masterIp, setMasterIp] = useState('');
  const [osTab, setOsTab] = useState('linux');
  const [siteName, setSiteName] = useState('');
  const [copiedTarget, setCopiedTarget] = useState('');

  useEffect(() => {
    setMasterIp(window.location.hostname || '');
  }, []);

  const masterUrl = useMemo(() => {
    if (typeof window === 'undefined') {
      return masterIp ? `http://${masterIp}:8000` : (API ? API.replace(/\/$/, '') : 'http://<master-ip>:8000');
    }

    if (!masterIp) {
      if (API) return API.replace(/\/$/, '');
      return window.location.origin.replace(/:(3000|4173|5173)$/, ':8000');
    }

    const { protocol, port } = window.location;
    const resolvedPort = ['3000', '4173', '5173'].includes(port) ? '8000' : port;
    return `${protocol}//${masterIp}${resolvedPort ? `:${resolvedPort}` : ''}`;
  }, [masterIp]);

  const downloadBase = useMemo(() => {
    if (typeof window === 'undefined') return 'http://<master-ip>';
    const host = masterIp || window.location.hostname || '<master-ip>';
    const { protocol, port } = window.location;
    return `${protocol}//${host}${port ? `:${port}` : ''}`;
  }, [masterIp]);

  const linuxPrefix = useMemo(() => siteName ? `PATCHMASTER_SITE="${siteName}" ` : '', [siteName]);
  const windowsSiteArg = useMemo(() => siteName ? ` --site "${siteName}"` : '', [siteName]);
  const linuxCmd = useMemo(() => `curl -sS ${downloadBase}/download/install-agent.sh | sudo ${linuxPrefix}MASTER_URL=${masterUrl} bash`, [downloadBase, linuxPrefix, masterUrl]);
  const windowsCmd = useMemo(() => `cd $env:TEMP\nRemove-Item .\\PatchMaster-Agent-Installer.exe -Force -ErrorAction SilentlyContinue\ncurl.exe -L -o PatchMaster-Agent-Installer.exe "${downloadBase}/download/patchmaster-agent-installer.exe"\n.\\PatchMaster-Agent-Installer.exe --master-url "${masterUrl}" --agent-port 18080${windowsSiteArg}`, [downloadBase, masterUrl, windowsSiteArg]);

  const siteEnvLine = useMemo(() => siteName ? `echo 'PATCHMASTER_SITE=${siteName}' | sudo tee -a /etc/patch-agent/env\n` : '', [siteName]);

  const manualTracks = useMemo(() => ([
    {
      title: 'Debian and Ubuntu',
      subtitle: 'Artifact: agent-latest.deb',
      icon: 'package',
      commands: `curl -fsSL -o agent-latest.deb ${downloadBase}/download/agent-latest.deb\nsudo dpkg -i agent-latest.deb || sudo apt-get install -f -y\n${siteEnvLine}sudo systemctl enable --now patch-agent patch-agent-heartbeat`,
    },
    {
      title: 'RPM distributions',
      subtitle: 'RHEL, Rocky, Alma, Fedora, Amazon Linux, openSUSE',
      icon: 'archive',
      commands: `curl -fsSL -o agent-latest.rpm ${downloadBase}/download/agent-latest.rpm\nsudo rpm -Uvh agent-latest.rpm || sudo dnf localinstall -y agent-latest.rpm || sudo zypper install -y ./agent-latest.rpm\n${siteEnvLine}sudo systemctl enable --now patch-agent patch-agent-api`,
    },
    {
      title: 'Arch Linux',
      subtitle: 'Artifact: agent-latest.pkg.tar.zst',
      icon: 'box',
      commands: `curl -fsSL -o agent-latest.pkg.tar.zst ${downloadBase}/download/agent-latest.pkg.tar.zst\nsudo pacman -U --noconfirm agent-latest.pkg.tar.zst\n${siteEnvLine}sudo systemctl enable --now patch-agent patch-agent-api`,
    },
    {
      title: 'Alpine Linux',
      subtitle: 'Artifact: agent-latest.apk',
      icon: 'layers',
      commands: `curl -fsSL -o agent-latest.apk ${downloadBase}/download/agent-latest.apk\nsudo apk add --allow-untrusted agent-latest.apk\n${siteEnvLine}sudo rc-update add patch-agent default\nsudo rc-update add patch-agent-api default\nsudo rc-service patch-agent start\nsudo rc-service patch-agent-api start`,
    },
    {
      title: 'FreeBSD',
      subtitle: 'Artifact: agent-latest.txz',
      icon: 'server',
      commands: `fetch -o agent-latest.txz ${downloadBase}/download/agent-latest.txz\nsudo pkg add agent-latest.txz\n${siteEnvLine ? `echo 'PATCHMASTER_SITE=${siteName}' | sudo tee -a /usr/local/etc/patch-agent/env\n` : ''}sudo sysrc patch_agent_enable="YES"\nsudo sysrc patch_agent_api_enable="YES"\nsudo service patch_agent start\nsudo service patch_agent_api start`,
    },
    {
      title: 'Windows',
      subtitle: 'Artifact: patchmaster-agent-installer.exe',
      icon: 'window',
      commands: `cd %TEMP%\ncurl.exe -L -o PatchMaster-Agent-Installer.exe "${downloadBase}/download/patchmaster-agent-installer.exe"\nPatchMaster-Agent-Installer.exe --master-url "${masterUrl}" --agent-port 18080${windowsSiteArg}`,
    },
  ]), [downloadBase, masterUrl, siteEnvLine, windowsSiteArg, siteName]);

  const rolloutChecklist = [
    {
      title: 'Confirm the master address resolves from the target subnet.',
      detail: 'The hostname or IP entered above is used in the copied commands.',
    },
    {
      title: 'Allow HTTP or HTTPS access to the Patch-SecOps Solution download endpoint.',
      detail: `Operators download packages from ${downloadBase}/download/.`,
    },
    {
      title: 'Use Linux bootstrap only for Debian/Ubuntu or RPM-based Linux hosts.',
      detail: 'Arch, Alpine, and FreeBSD are supported through the manual package tracks below.',
    },
    {
      title: 'Use the package that matches the shipped artifact for that platform.',
      detail: 'This page exposes the current DEB, RPM, PKG.TAR.ZST, APK, TXZ, and EXE artifacts only.',
    },
    {
      title: 'For Windows, use dedicated agent API port 18080 to avoid common 8080 conflicts.',
      detail: 'The Windows installer commands on this page already set that port.',
    },
  ];

  const verifySnippets = [
    {
      title: 'Systemd Linux validation',
      icon: 'shield',
      subtitle: 'Use for Debian, Ubuntu, RPM distributions, and Arch packages.',
      commands: 'sudo systemctl status patch-agent patch-agent-heartbeat patch-agent-api\nsudo journalctl -u patch-agent -u patch-agent-heartbeat -u patch-agent-api -n 80 --no-pager',
    },
    {
      title: 'Alpine validation',
      icon: 'layers',
      subtitle: 'Use for Alpine packages installed through OpenRC.',
      commands: 'sudo rc-service patch-agent status\nsudo rc-service patch-agent-api status\nsudo tail -n 80 /var/log/patch-agent/* 2>/dev/null',
    },
    {
      title: 'FreeBSD validation',
      icon: 'server',
      subtitle: 'Use for FreeBSD packages installed through rc.d.',
      commands: 'sudo service patch_agent status\nsudo service patch_agent_api status\nsudo tail -n 80 /var/log/patch-agent/* 2>/dev/null',
    },
    {
      title: 'Windows validation',
      icon: 'terminal',
      subtitle: 'Verify services and the local health endpoint after install.',
      commands: 'Get-Service PatchMaster-Agent,PatchMaster-Agent-Heartbeat\ncurl.exe -sS http://127.0.0.1:18080/health\nGet-Content "$env:ProgramData\\PatchMaster-Agent\\logs\\PatchMaster-Agent-Heartbeat.out.log" -Tail 80',
    },
  ];

  const copyText = async (label, value) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedTarget(label);
      window.setTimeout(() => setCopiedTarget(''), 1800);
    } catch {
      setCopiedTarget('');
    }
  };

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#93c5fd', background: 'linear-gradient(145deg, #eff6ff, #f8fbff)' }}>
          <div className="ops-kicker">Onboarding operations</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Install target</span>
              <span className="ops-emphasis-value" style={{ color: '#1d4ed8', fontSize: 26 }}>{masterIp || '<master-ip>'}</span>
              <span className="ops-emphasis-meta">Use the same address your agents can reach from production networks.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Bring new hosts online with a clean, repeatable runbook.</h3>
              <p>
                This onboarding workspace gives operators one place to copy quick Linux and Windows install commands, plus manual package steps for Debian/Ubuntu, RPM-based Linux, Arch, Alpine, FreeBSD, and Windows.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">Linux bootstrap</span>
            <span className="ops-chip">Windows installer</span>
            <span className="ops-chip">DEB, RPM, PKG, APK, TXZ, EXE</span>
            <span className="ops-chip">Validation commands</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Deployment profile</span>
          <div className="ops-side-metric">Ready</div>
          <p className="ops-side-note">
            Set the master address once, then copy the exact command or package steps needed for the target platform. The counts below are derived from the install paths currently shipped in this repo.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>2</strong>
              <span>quick install commands</span>
            </div>
            <div className="ops-inline-card">
              <strong>{manualTracks.length}</strong>
              <span>manual package tracks</span>
            </div>
            <div className="ops-inline-card">
              <strong>{verifySnippets.length}</strong>
              <span>validation blocks</span>
            </div>
            <div className="ops-inline-card">
              <strong>{siteName ? 'Tagged' : 'Optional'}</strong>
              <span>site stamp in env file</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {[
          { label: 'Master address', value: masterIp || '<master-ip>', sub: 'used in every install command', icon: 'server', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
          { label: 'Quick install', value: '2 paths', sub: 'Linux bootstrap and Windows installer', icon: 'terminal', color: '#0f766e', bg: 'rgba(16,185,129,0.12)' },
          { label: 'Packaged artifacts', value: `${manualTracks.length}`, sub: 'DEB, RPM, PKG.TAR.ZST, APK, TXZ, and EXE', icon: 'archive', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
          { label: 'Validation', value: `${verifySnippets.length} blocks`, sub: 'systemd, OpenRC, rc.d, and Windows checks', icon: 'shield', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
        ].map(card => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value" style={{ fontSize: card.label === 'Master address' ? 22 : 28 }}>{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Quick install</div>
            <p className="ops-subtle">Copy a ready-to-run command for Linux or Windows. The Linux bootstrap script currently covers Debian/Ubuntu and RPM-based distributions. Use the manual package section for Arch, Alpine, and FreeBSD.</p>
          </div>
        </div>
        <div className="ops-form-grid">
          <div>
            <label className="ops-side-label">Master IP or hostname</label>
            <input className="input" value={masterIp} onChange={(e) => setMasterIp(e.target.value)} placeholder="e.g. 10.20.30.40" />
          </div>
          <div>
            <label className="ops-side-label">Site or location</label>
            <input className="input" value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="e.g. Singapore-DC / Mumbai-HQ / London-Branch" />
          </div>
        </div>
        <div className="ops-pills" style={{ marginTop: 16 }}>
          <button className={`ops-pill ${osTab === 'linux' ? 'active' : ''}`} onClick={() => setOsTab('linux')}>Linux</button>
          <button className={`ops-pill ${osTab === 'windows' ? 'active' : ''}`} onClick={() => setOsTab('windows')}>Windows</button>
        </div>
        <div className="ops-command-card" style={{ marginTop: 16 }}>
          <div className="ops-table-toolbar" style={{ marginBottom: 12 }}>
            <div>
              <div className="ops-panel-title" style={{ fontSize: 16 }}>{osTab === 'linux' ? 'Linux bootstrap command' : 'Windows installer command'}</div>
              <p className="ops-subtle" style={{ marginTop: 6 }}>
                Downloads are served from <code>{downloadBase}/download/</code>, and the installer registers back to <code>{masterUrl}</code>.
              </p>
            </div>
            <button className={`btn btn-sm ${copiedTarget === osTab ? 'btn-success' : 'btn-primary'}`} onClick={() => copyText(osTab, osTab === 'linux' ? linuxCmd : windowsCmd)}>
              {copiedTarget === osTab ? 'Copied' : 'Copy command'}
            </button>
          </div>
          <pre className="code-block">{osTab === 'linux' ? linuxCmd : windowsCmd}</pre>
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Manual package paths</div>
              <p className="ops-subtle">Use these when the quick bootstrap path does not match the target OS, or when operators need an explicit package install flow. These tracks map to the artifacts currently shipped in backend/static.</p>
            </div>
          </div>
          <div className="ops-list">
            {manualTracks.map(track => (
              <div key={track.title} className="ops-command-card">
                <div className="ops-table-toolbar" style={{ marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="ops-summary-icon" style={{ color: '#1d4ed8', background: 'rgba(59,130,246,0.12)' }}>
                      <AppIcon name={track.icon} size={17} />
                    </span>
                    <div>
                      <div className="ops-panel-title" style={{ fontSize: 16 }}>{track.title}</div>
                      <div className="ops-subtle" style={{ marginTop: 4 }}>{track.subtitle}</div>
                    </div>
                  </div>
                  <button className={`btn btn-sm ${copiedTarget === track.title ? 'btn-success' : ''}`} onClick={() => copyText(track.title, track.commands)}>
                    {copiedTarget === track.title ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <pre className="code-block">{track.commands}</pre>
              </div>
            ))}
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Deployment readiness</div>
              <p className="ops-subtle">Use this as the handoff checklist before you ask platform teams to roll out agents at scale.</p>
            </div>
          </div>
          <div className="ops-list">
            {rolloutChecklist.map(item => (
              <div key={item.title} className="ops-list-item">
                <div className="ops-list-copy">
                  <strong>{item.title}</strong>
                  <span>{item.detail}</span>
                </div>
                <div className="ops-list-metrics">
                  <span className="badge badge-info">Ready check</span>
                </div>
              </div>
            ))}
          </div>
          <div className="ops-table-toolbar" style={{ marginTop: 24 }}>
            <div>
              <div className="ops-panel-title">Verify first check-in</div>
              <p className="ops-subtle">Once the installer finishes, confirm the local services are running and then verify the host appears in Hosts.</p>
            </div>
          </div>
          <div className="ops-list">
            {verifySnippets.map(block => (
              <div key={block.title} className="ops-command-card">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <span className="ops-summary-icon" style={{ color: '#0f766e', background: 'rgba(16,185,129,0.12)' }}>
                    <AppIcon name={block.icon} size={17} />
                  </span>
                  <div>
                    <div className="ops-panel-title" style={{ fontSize: 16 }}>{block.title}</div>
                    <div className="ops-subtle" style={{ marginTop: 4 }}>{block.subtitle}</div>
                  </div>
                </div>
                <pre className="code-block">{block.commands}</pre>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
