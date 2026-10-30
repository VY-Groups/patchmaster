import React, { useMemo, useState } from 'react';
import './OpsPages.css';

export default function SettingsOpsPage({ health, hosts, jobs, API, apiFetch, AppIcon }) {
  // Defensive checks: ensure arrays are always arrays
  const safeHosts = Array.isArray(hosts) ? hosts : [];
  const safeJobs = Array.isArray(jobs) ? jobs : [];
  
  const [changePw, setChangePw] = useState({ current: '', new_password: '', confirm_password: '' });
  const [pwMsg, setPwMsg] = useState('');
  const [saving, setSaving] = useState(false);
  const [copiedKey, setCopiedKey] = useState('');

  const masterIp = typeof window !== 'undefined' ? window.location.hostname : '<master-ip>';
  const frontendUrl = typeof window !== 'undefined' ? window.location.origin : 'http://<master-ip>';
  const controllerUrl = (API || `http://${masterIp}:8000`).replace(/\/$/, '');

  const commandDeck = useMemo(() => ([
    {
      key: 'linux',
      title: 'Linux quick install',
      icon: 'terminal',
      description: 'Bootstrap a Linux host directly from the control plane download endpoint.',
      commands: `curl -sS ${frontendUrl}/download/install-agent.sh | sudo MASTER_URL=${controllerUrl} bash`,
    },
    {
      key: 'windows',
      title: 'Windows quick install',
      icon: 'window',
      description: 'Use this from Command Prompt as Administrator or package it in your endpoint tooling.',
      commands: `cd $env:TEMP\nRemove-Item .\\PatchMaster-Agent-Installer.exe -Force -ErrorAction SilentlyContinue\ncurl.exe -L -o PatchMaster-Agent-Installer.exe "${frontendUrl}/download/patchmaster-agent-installer.exe"\n.\\PatchMaster-Agent-Installer.exe --master-url "${controllerUrl}" --agent-port 18080`,
    },
    {
      key: 'docker',
      title: 'Docker operations',
      icon: 'layers',
      description: 'Common lifecycle commands for containerized Patch-SecOps Solution deployments.',
      commands: 'docker compose build --no-cache\ndocker compose up -d\ndocker compose logs -f backend\ndocker compose down',
    },
  ]), [controllerUrl, frontendUrl]);

  const endpoints = [
    { label: 'Frontend', value: frontendUrl, icon: 'window' },
    { label: 'API base', value: API, icon: 'server' },
    { label: 'Metrics', value: `${API.replace(/\/$/, '')}/metrics`, icon: 'timeline' },
    { label: 'Master host', value: masterIp, icon: 'server' },
  ];

  const copyText = async (key, value) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(''), 1800);
    } catch {
      setCopiedKey('');
    }
  };

  const changePassword = async () => {
    if (changePw.new_password !== changePw.confirm_password) {
      setPwMsg('New passwords do not match.');
      return;
    }
    if (changePw.new_password.length < 8) {
      setPwMsg('Password must be at least 8 characters.');
      return;
    }

    setSaving(true);
    setPwMsg('');
    try {
      const response = await apiFetch(`${API}/api/auth/change-password`, {
        method: 'POST',
        body: JSON.stringify({
          old_password: changePw.current,
          new_password: changePw.new_password,
        }),
      });
      if (response.ok) {
        setPwMsg('Password changed successfully.');
        setChangePw({ current: '', new_password: '', confirm_password: '' });
      } else {
        const payload = await response.json().catch(() => ({}));
        setPwMsg(payload.detail || 'Password update failed.');
      }
    } catch (error) {
      setPwMsg(`Error: ${error.message}`);
    } finally {
      setSaving(false);
    }
  };

  const backendOnline = Boolean(health);
  const version = health?.version || '2.0.0';

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: backendOnline ? '#86efac' : '#fca5a5', background: backendOnline ? 'linear-gradient(145deg, #ecfdf3, #f8fffb)' : 'linear-gradient(145deg, #fef2f2, var(--card-bg)7f7)' }}>
          <div className="ops-kicker">Platform settings</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Control plane</span>
              <span className="ops-emphasis-value" style={{ color: backendOnline ? '#166534' : '#b91c1c', fontSize: 28 }}>
                {backendOnline ? 'Online' : 'Offline'}
              </span>
              <span className="ops-emphasis-meta">Version {version} - master {masterIp}</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Keep the Patch-SecOps Solution control plane clean, secure, and easy to operate.</h3>
              <p>
                Settings is now structured like an admin workspace: environment visibility up top, credential maintenance in the middle, and reusable operational commands alongside the endpoints your team relies on every day.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">{hosts.length} managed hosts</span>
            <span className="ops-chip">{jobs.length} jobs tracked</span>
            <span className="ops-chip">API base {API}</span>
            <span className="ops-chip">Account security controls</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Environment posture</span>
          <div className="ops-side-metric">{backendOnline ? 'Healthy' : 'Needs review'}</div>
          <p className="ops-side-note">
            Use this page for administrator hygiene: confirm service reachability, rotate credentials, and give your team one reliable place for bootstrap and recovery commands.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>{hosts.length}</strong>
              <span>registered hosts</span>
            </div>
            <div className="ops-inline-card">
              <strong>{jobs.length}</strong>
              <span>job records</span>
            </div>
            <div className="ops-inline-card">
              <strong>{backendOnline ? 'Up' : 'Down'}</strong>
              <span>backend heartbeat</span>
            </div>
            <div className="ops-inline-card">
              <strong>{version}</strong>
              <span>current release</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {[
          { label: 'Backend status', value: backendOnline ? 'Online' : 'Offline', sub: 'service reachability from the UI', icon: 'server', color: backendOnline ? '#16a34a' : '#dc2626', bg: backendOnline ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)' },
          { label: 'Master host', value: masterIp, sub: 'agent-facing control plane address', icon: 'server', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
          { label: 'Managed hosts', value: hosts.length, sub: 'fleet size reflected in Patch-SecOps Solution', icon: 'users', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
          { label: 'Tracked jobs', value: jobs.length, sub: 'execution history and active queue', icon: 'timeline', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
        ].map(card => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value" style={{ fontSize: typeof card.value === 'string' && card.value.length > 10 ? 22 : 28 }}>{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Account security</div>
              <p className="ops-subtle">Rotate the current user password without leaving the admin workspace.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <input className="input" type="password" placeholder="Current password" value={changePw.current} onChange={(e) => setChangePw((prev) => ({ ...prev, current: e.target.value }))} />
            <input className="input" type="password" placeholder="New password (min 8 chars)" value={changePw.new_password} onChange={(e) => setChangePw((prev) => ({ ...prev, new_password: e.target.value }))} />
            <input className="input" type="password" placeholder="Confirm new password" value={changePw.confirm_password} onChange={(e) => setChangePw((prev) => ({ ...prev, confirm_password: e.target.value }))} />
          </div>
          <div className="ops-actions" style={{ marginTop: 14 }}>
            <button className="btn btn-primary" onClick={changePassword} disabled={saving}>
              {saving ? 'Updating...' : 'Change password'}
            </button>
          </div>
          {pwMsg && (
            <div
              className="ops-command-card"
              style={{
                marginTop: 16,
                borderColor: pwMsg.toLowerCase().includes('success') ? '#86efac' : '#fecaca',
                background: pwMsg.toLowerCase().includes('success') ? 'linear-gradient(145deg, #ecfdf3, #f8fffb)' : 'linear-gradient(145deg, var(--card-bg)7ed, var(--card-bg)df8)',
              }}
            >
              <div style={{ color: pwMsg.toLowerCase().includes('success') ? '#166534' : '#b45309', fontWeight: 700 }}>{pwMsg}</div>
            </div>
          )}
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Environment endpoints</div>
              <p className="ops-subtle">Useful addresses for quick checks, troubleshooting, and handoff to operators.</p>
            </div>
          </div>
          <div className="ops-list">
            {endpoints.map((item) => (
              <div key={item.label} className="ops-list-item">
                <div className="ops-list-copy">
                  <strong>{item.label}</strong>
                  <span>{item.value}</span>
                </div>
                <div className="ops-list-metrics">
                  <span className="ops-summary-icon" style={{ color: '#1d4ed8', background: 'rgba(59,130,246,0.12)' }}>
                    <AppIcon name={item.icon} size={17} />
                  </span>
                  <button className={`btn btn-sm ${copiedKey === item.label ? 'btn-success' : ''}`} onClick={() => copyText(item.label, item.value)}>
                    {copiedKey === item.label ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Operations command deck</div>
            <p className="ops-subtle">Keep the most-used platform commands close by so onboarding and recovery steps stay consistent.</p>
          </div>
        </div>
        <div className="ops-list">
          {commandDeck.map((block) => (
            <div key={block.key} className="ops-command-card">
              <div className="ops-table-toolbar" style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="ops-summary-icon" style={{ color: '#1d4ed8', background: 'rgba(59,130,246,0.12)' }}>
                    <AppIcon name={block.icon} size={18} />
                  </span>
                  <div>
                    <div className="ops-panel-title" style={{ fontSize: 16 }}>{block.title}</div>
                    <p className="ops-subtle" style={{ marginTop: 4 }}>{block.description}</p>
                  </div>
                </div>
                <button className={`btn btn-sm ${copiedKey === block.key ? 'btn-success' : 'btn-primary'}`} onClick={() => copyText(block.key, block.commands)}>
                  {copiedKey === block.key ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="code-block">{block.commands}</pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
