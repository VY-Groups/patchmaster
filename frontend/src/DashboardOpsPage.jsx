import React, { useCallback, useEffect, useState } from 'react';
import './OpsPages.css';

// Lightweight health ring endpoint for frequent polling
const REFRESH_INTERVAL = 10000; // 10 seconds

export default function DashboardOpsPage({
  health,
  hosts,
  jobs,
  setPage,
  API,
  apiFetch,
  useInterval,
  AppIcon,
  RiskGauge,
  PatchVelocityChart,
}) {
  // Defensive checks: ensure arrays are always arrays
  const safeHosts = Array.isArray(hosts) ? hosts : [];
  const safeJobs = Array.isArray(jobs) ? jobs : [];
  
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isVisible, setIsVisible] = useState(true);

  const fetchSummary = useCallback(() => {
    // Only fetch when tab is visible to reduce unnecessary load
    if (!isVisible || document.hidden) return;
    setLoading(true);
    apiFetch(`${API}/api/dashboard/summary`)
      .then(r => r.json())
      .then(d => {
        setSummary(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [API, apiFetch, isVisible]);

  // Visibility API: only poll when tab is visible
  useEffect(() => {
    const handleVisibility = () => {
      setIsVisible(!document.hidden);
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, []);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  useInterval(fetchSummary, REFRESH_INTERVAL);

  if (loading && !summary) {
    return <div className="ops-empty">Loading dashboard...</div>;
  }

  if (!safeHosts.length) {
    return (
      <div className="ops-shell">
        <div className="ops-panel" style={{ textAlign: 'center', padding: '56px 32px' }}>
          <span
            aria-hidden="true"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 82,
              height: 82,
              borderRadius: 24,
              background: 'linear-gradient(145deg, #eff6ff, #dbeafe)',
              color: '#1d4ed8',
              boxShadow: '0 14px 30px rgba(37,99,235,0.16)',
              marginBottom: 20,
            }}
          >
            <AppIcon name="dashboard" size={34} />
          </span>
          <h2 style={{ fontSize: '2rem', marginBottom: 12, color: 'var(--text-primary)' }}>Welcome to Patch-SecOps Solution</h2>
          <p style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', maxWidth: 620, margin: '0 auto 28px', lineHeight: 1.75 }}>
            No agents are registered yet. Once hosts are online, this command center will show live compliance posture, CVE exposure, patch velocity, and remediation workload.
          </p>
          <button className="btn btn-primary btn-lg" onClick={() => setPage('onboarding')}>
            Start Setup
          </button>
        </div>
      </div>
    );
  }

  const s = summary || {};
  const running = safeJobs.filter(job => job.status === 'running').length;
  const pending = safeJobs.filter(job => job.status === 'pending' || job.status === 'scheduled').length;

  // Backend returns flat keys — map them correctly
  const totalHosts = s.total_hosts ?? safeHosts.length;
  const onlineHosts = s.online_hosts ?? 0;
  const avgCompliance = s.avg_compliance ?? 0;
  const criticalCves = s.critical_cves ?? 0;
  const rebootRequired = s.reboot_required ?? 0;
  const openVulns = s.total_cves ?? 0;
  const upgradable = s.total_upgradable ?? 0;
  const riskScore = s.risk_score ?? 0;
  const success30d = s.success_jobs_30d ?? 0;
  const failed30d = s.failed_jobs_30d ?? 0;
  const patchSuccessRate = success30d + failed30d ? Math.round((success30d / (success30d + failed30d)) * 100) : 0;

  // Calculate platform distribution
  const platformCounts = safeHosts.reduce((acc, host) => {
    const osText = (host.os || '').toLowerCase();
    const groups = (host.groups || []).map(g => (g || '').toLowerCase());
    
    if (groups.includes('windows') || osText.includes('windows')) acc.windows++;
    else if (groups.includes('debian/ubuntu') || osText.includes('ubuntu') || osText.includes('debian')) acc.debian++;
    else if (groups.includes('rhel/rpm') || osText.includes('rhel') || osText.includes('centos') || osText.includes('rocky') || osText.includes('alma') || osText.includes('fedora') || osText.includes('amazon linux')) acc.rhel++;
    else if (groups.includes('arch') || osText.includes('arch') || osText.includes('manjaro') || osText.includes('endeavour')) acc.arch++;
    else if (groups.includes('opensuse') || osText.includes('opensuse') || osText.includes('suse')) acc.opensuse++;
    else if (groups.includes('alpine') || osText.includes('alpine')) acc.alpine++;
    else if (groups.includes('freebsd') || osText.includes('freebsd') || osText.includes('bsd')) acc.freebsd++;
    else acc.other++;
    
    return acc;
  }, { windows: 0, debian: 0, rhel: 0, arch: 0, opensuse: 0, alpine: 0, freebsd: 0, other: 0 });

  const posture = riskScore >= 80
    ? {
        title: 'High operational risk',
        description: 'Critical exposure or weak patch hygiene is pulling the fleet into an at-risk state. Prioritize vulnerable hosts and restart backlog.',
        tone: '#b91c1c',
        bg: 'linear-gradient(145deg, #fef2f2, var(--card-bg)7f7)',
        border: '#fca5a5',
      }
    : riskScore >= 55
      ? {
          title: 'Mixed operating posture',
          description: 'The estate is generally stable, but risk is concentrated in a subset of hosts. Use the queues below to focus remediation.',
          tone: '#b45309',
          bg: 'linear-gradient(145deg, var(--card-bg)beb, var(--card-bg)df5)',
          border: '#fcd34d',
        }
      : {
          title: 'Healthy operational posture',
          description: 'Fleet health and vulnerability pressure are within target. Keep feeds fresh and maintain execution quality.',
          tone: '#166534',
          bg: 'linear-gradient(145deg, #ecfdf3, #f8fffb)',
          border: '#86efac',
        };

  const summaryCards = [
    { label: 'Managed Hosts', value: totalHosts, sub: `${onlineHosts} reporting live`, icon: 'server', color: '#2563eb', bg: 'rgba(37,99,235,0.12)', page: 'hosts' },
    { label: 'Patch Compliance', value: `${avgCompliance}%`, sub: `${rebootRequired} waiting for reboot`, icon: 'shield', color: '#0f766e', bg: 'rgba(16,185,129,0.12)', page: 'compliance' },
    { label: 'Critical CVEs', value: criticalCves, sub: `${openVulns} open vulnerabilities`, icon: 'bug', color: '#dc2626', bg: 'rgba(239,68,68,0.12)', page: 'cve' },
    { label: 'Patch Queue', value: upgradable, sub: `${running} jobs running now`, icon: 'package', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)', page: 'patches' },
    { label: 'Execution Quality', value: `${patchSuccessRate}%`, sub: `${success30d} success / ${failed30d} failed`, icon: 'timeline', color: '#1d4ed8', bg: 'rgba(59,130,246,0.12)', page: 'jobs' },
    { label: 'Pending Work', value: pending, sub: 'scheduled or pending jobs', icon: 'calendar', color: '#d97706', bg: 'rgba(245,158,11,0.14)', page: 'jobs' },
  ];

  const attentionItems = Array.isArray(s.needs_attention) ? s.needs_attention : [];
  const vulnerableHosts = Array.isArray(s.top_vulnerable) ? s.top_vulnerable : [];
  const recentActivity = Array.isArray(s.recent_activity) ? s.recent_activity.slice(0, 8) : [];

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: posture.border, background: posture.bg }}>
          <div className="ops-kicker">Operations command center</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Risk score</span>
              <span className="ops-emphasis-value" style={{ color: posture.tone }}>{riskScore}</span>
              <span className="ops-emphasis-meta">{criticalCves} critical CVEs and {rebootRequired} restart actions pending</span>
            </div>
            <div className="ops-hero-copy">
              <h3>{posture.title}</h3>
              <p>{posture.description}</p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">{totalHosts} managed hosts</span>
            <span className="ops-chip">{onlineHosts} online right now</span>
            <span className="ops-chip">{running} active patch jobs</span>
            <span className="ops-chip">{openVulns} open vulnerabilities</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Platform status</span>
          <div className="ops-side-metric">{health ? 'Online' : 'Offline'}</div>
          <p className="ops-side-note">
            {health ? `Backend responding - version ${health.version || '2.0.0'}` : 'Backend health data is unavailable. Check services and connectivity.'}
          </p>
          <div className="ops-inline-list">
            {[
              { label: 'Running jobs', value: running },
              { label: 'Pending jobs', value: pending },
              { label: 'Upgradable pkgs', value: upgradable },
              { label: 'Patch success', value: `${patchSuccessRate}%` },
            ].map(item => (
              <div key={item.label} className="ops-inline-card">
                <strong>{item.value}</strong>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {summaryCards.map(card => (
          <div
            key={card.label}
            className="ops-summary-card"
            onClick={() => card.page && setPage(card.page)}
            style={{ cursor: card.page ? 'pointer' : 'default' }}
          >
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value">{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      {/* Platform Distribution Panel */}
      <div className="ops-panel" style={{ marginBottom: 24 }}>
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Platform Distribution</div>
            <p className="ops-subtle">Universal support across all major operating systems - {totalHosts} hosts managed</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '16px 0' }}>
          {[
            { key: 'windows', label: 'Windows', icon: 'windows', color: '#0078d4' },
            { key: 'debian', label: 'Debian/Ubuntu', icon: 'linux', color: '#d70a53' },
            { key: 'rhel', label: 'RHEL/RPM', icon: 'rhel', color: '#ee0000' },
            { key: 'arch', label: 'Arch Linux', icon: 'arch', color: '#1793d1' },
            { key: 'opensuse', label: 'openSUSE', icon: 'opensuse', color: '#73ba25' },
            { key: 'alpine', label: 'Alpine', icon: 'alpine', color: '#0d597f' },
            { key: 'freebsd', label: 'FreeBSD', icon: 'freebsd', color: '#ab2b28' },
            { key: 'other', label: 'Other', icon: 'other', color: 'var(--text-secondary)' },
          ].map(platform => {
            const count = platformCounts[platform.key] || 0;
            const loadedTotal = Object.values(platformCounts).reduce((a, b) => a + b, 0) || 1;
            const percentage = Math.round((count / loadedTotal) * 100);
            
            return (
              <div
                key={platform.key}
                style={{
                  flex: '1 1 200px',
                  minWidth: 180,
                  padding: 16,
                  border: '1px solid var(--border-color)',
                  borderRadius: 8,
                  background: count > 0 ? 'var(--card-bg)' : '#f8fafc',
                  opacity: count > 0 ? 1 : 0.6,
                  transition: 'all 0.2s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: platform.color }}>{platform.key.charAt(0).toUpperCase()}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{platform.label}</span>
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: platform.color, marginBottom: 4 }}>
                  {count}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  {percentage}% of fleet
                </div>
                {count > 0 && (
                  <div style={{ marginTop: 8, height: 4, background: 'var(--border-color)', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', background: platform.color, width: `${percentage}%`, transition: 'width 0.3s' }} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div style={{ padding: '12px 0 0', borderTop: '1px solid var(--border-color)', marginTop: 8 }}>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0 }}>
            ✅ <strong>{Object.values(platformCounts).filter(c => c > 0).length} platforms active</strong> - Distribution based on loaded fleet data
          </p>
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Risk and velocity</div>
              <p className="ops-subtle">Track overall fleet pressure and how effectively the team is closing patch work week over week.</p>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '0 0 auto' }}>
              <RiskGauge score={riskScore} />
            </div>
            <div style={{ flex: 1, minWidth: 260 }}>
              <PatchVelocityChart data={s?.patch_velocity} />
              <div className="ops-inline-list" style={{ marginTop: 16 }}>
                <div className="ops-inline-card">
                  <strong>{success30d}</strong>
                  <span>successful jobs in 30 days</span>
                </div>
                <div className="ops-inline-card">
                  <strong>{failed30d}</strong>
                  <span>failed jobs in 30 days</span>
                </div>
                <div className="ops-inline-card">
                  <strong>{pending}</strong>
                  <span>pending remediation items</span>
                </div>
                <div className="ops-inline-card">
                  <strong>{patchSuccessRate}%</strong>
                  <span>execution success rate</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Needs attention</div>
              <p className="ops-subtle">The fastest path to reducing risk is to clear these hosts first.</p>
            </div>
          </div>
          {!attentionItems.length ? (
            <div className="ops-empty">All monitored hosts are healthy.</div>
          ) : (
            <div className="ops-list">
              {attentionItems.map(item => (
                <div key={item.id} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{item.hostname}</strong>
                    <span>{item.cve_count} CVE{item.cve_count !== 1 ? 's' : ''} · last seen {item.last_heartbeat ? new Date(item.last_heartbeat).toLocaleString() : 'never'}</span>
                  </div>
                  <div className="ops-list-metrics">
                    <span className="badge badge-danger">Offline</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Top vulnerable hosts</div>
              <p className="ops-subtle">These hosts combine the highest CVE pressure with lower patch posture.</p>
            </div>
          </div>
          {!vulnerableHosts.length ? (
            <div className="ops-empty">No CVE data yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="table ops-table">
                <thead>
                  <tr><th>Host</th><th>CVEs</th><th>Compliance</th></tr>
                </thead>
                <tbody>
                  {vulnerableHosts.map(host => (
                    <tr key={host.id}>
                      <td>
                        <strong>{host.hostname}</strong>
                        <span className="ops-table-meta">{host.is_online ? 'Online' : 'Offline'}</span>
                      </td>
                      <td><span className={`badge badge-${host.cve_count > 10 ? 'danger' : host.cve_count > 3 ? 'warning' : 'info'}`}>{host.cve_count}</span></td>
                      <td><span className={`badge badge-${host.compliance_score >= 90 ? 'success' : host.compliance_score >= 70 ? 'warning' : 'danger'}`}>{host.compliance_score}%</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Recent activity</div>
              <p className="ops-subtle">A quick read of operational movement across jobs, admin actions, and system events.</p>
            </div>
          </div>
          {!recentActivity.length ? (
            <div className="ops-empty">No recent activity.</div>
          ) : (
            <div className="ops-list">
              {recentActivity.map(item => (
                <div key={item.id} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{item.hostname || `host#${item.host_id}`}</strong>
                    <span>{item.action}</span>
                  </div>
                  <div className="ops-list-metrics">
                    <span className={`badge badge-${item.status === 'success' ? 'success' : item.status === 'failed' ? 'danger' : 'info'}`}>{item.status}</span>
                    <span className="ops-chip">{item.created_at ? new Date(item.created_at).toLocaleTimeString() : ''}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Quick actions</div>
            <p className="ops-subtle">Jump directly into the workflows most teams use during daily patch operations.</p>
          </div>
        </div>
        <div className="ops-actions">
          <button className="btn btn-primary" onClick={() => setPage('patches')}>Patch Servers</button>
          <button className="btn btn-primary" onClick={() => setPage('compliance')}>Compliance</button>
          <button className="btn btn-primary" onClick={() => setPage('cve')}>CVE Tracker</button>
          <button className="btn btn-primary" onClick={() => setPage('hosts')}>Hosts</button>
          <button className="btn btn-success" onClick={() => setPage('onboarding')}>Onboard Host</button>
        </div>
      </div>
    </div>
  );
}

{/* placeholder */}
