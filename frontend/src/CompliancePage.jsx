import React, { useState, useEffect, useCallback, useMemo } from 'react';

export function CompliancePage({ API, apiFetch, AppIcon }) {
  const [overview, setOverview] = useState(null);
  const [byGroup, setByGroup] = useState([]);
  const [hostDetail, setHostDetail] = useState([]);
  const [view, setView] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [hostQuery, setHostQuery] = useState('');
  // Task 10: Filter persistence - load from localStorage
  const [hostFilter, setHostFilter] = useState(() => {
    try {
      return localStorage.getItem('pm_compliance_host_filter') || 'all';
    } catch { return 'all'; }
  });

  // Task 10: Save filter to localStorage when it changes
  const handleHostFilterChange = (value) => {
    setHostFilter(value);
    try {
      localStorage.setItem('pm_compliance_host_filter', value);
    } catch { /* ignore storage errors */}
  };

  const refreshCompliance = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiFetch(`${API}/api/compliance/overview`).then(r => r.json()).catch(() => null),
      apiFetch(`${API}/api/compliance/by-group`).then(r => r.json()).catch(() => []),
      apiFetch(`${API}/api/compliance/hosts-detail`).then(r => r.json()).catch(() => []),
    ]).then(([overviewData, byGroupData, hostData]) => {
      setOverview(overviewData);
      setByGroup(Array.isArray(byGroupData) ? byGroupData : []);
      setHostDetail(Array.isArray(hostData) ? hostData : []);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refreshCompliance();
  }, [refreshCompliance]);

  const safeOverview = overview || {
    total_hosts: 0,
    online_hosts: 0,
    avg_compliance: 0,
    reboot_required: 0,
    total_upgradable: 0,
    cves: { critical: 0, high: 0, medium: 0 },
    jobs_30d: { success: 0, failed: 0 },
    compliance_distribution: { fully_patched: 0, mostly_patched: 0, needs_attention: 0 },
  };

  const totalHosts = safeOverview.total_hosts || 0;
  const onlineHosts = safeOverview.online_hosts || 0;
  const avgCompliance = Number(safeOverview.avg_compliance || 0);
  const rebootRequired = safeOverview.reboot_required || 0;
  const totalUpgradable = safeOverview.total_upgradable || 0;
  const criticalCves = safeOverview.cves?.critical || 0;
  const highCves = safeOverview.cves?.high || 0;
  const jobsSuccess = safeOverview.jobs_30d?.success || 0;
  const jobsFailed = safeOverview.jobs_30d?.failed || 0;
  const fullyPatched = safeOverview.compliance_distribution?.fully_patched || 0;
  const mostlyPatched = safeOverview.compliance_distribution?.mostly_patched || 0;
  const needsAttention = safeOverview.compliance_distribution?.needs_attention || 0;
  const coveragePct = totalHosts ? Math.round((onlineHosts / totalHosts) * 100) : 0;
  const jobTotal = jobsSuccess + jobsFailed;
  const successRate = jobTotal ? Math.round((jobsSuccess / jobTotal) * 100) : 0;

  const posture = avgCompliance >= 95
    ? {
        title: 'Strong posture',
        description: 'Most systems are fully patched and active risk is tightly controlled.',
        tone: '#166534',
        bg: '#ecfdf3',
        border: '#86efac',
      }
    : avgCompliance >= 85
      ? {
          title: 'Controlled posture',
          description: 'Patch compliance is healthy, but there is still a visible remediation queue.',
          tone: '#1d4ed8',
          bg: '#eff6ff',
          border: '#93c5fd',
        }
      : avgCompliance >= 70
        ? {
            title: 'Watch posture',
            description: 'Fleet health is mixed. Prioritize hosts below target and reduce open backlog.',
            tone: '#b45309',
            bg: '#fffbeb',
            border: '#fcd34d',
          }
        : {
            title: 'At-risk posture',
            description: 'Compliance is below target and needs immediate remediation planning.',
            tone: '#b91c1c',
            bg: '#fef2f2',
            border: '#fca5a5',
          };

  const distributionRows = [
    {
      key: 'fully',
      label: 'Fully Patched',
      hint: '100%',
      count: fullyPatched,
      percent: totalHosts ? Math.round((fullyPatched / totalHosts) * 100) : 0,
      color: '#16a34a',
      bg: 'rgba(34,197,94,0.14)',
    },
    {
      key: 'mostly',
      label: 'Mostly Patched',
      hint: '80-99%',
      count: mostlyPatched,
      percent: totalHosts ? Math.round((mostlyPatched / totalHosts) * 100) : 0,
      color: '#d97706',
      bg: 'rgba(245,158,11,0.14)',
    },
    {
      key: 'attention',
      label: 'Needs Attention',
      hint: '<80%',
      count: needsAttention,
      percent: totalHosts ? Math.round((needsAttention / totalHosts) * 100) : 0,
      color: '#dc2626',
      bg: 'rgba(239,68,68,0.14)',
    },
  ];

  const summaryCards = [
    {
      label: 'Fleet Coverage',
      value: `${coveragePct}%`,
      sub: `${onlineHosts} of ${totalHosts} hosts reporting`,
      icon: 'server',
      color: '#2563eb',
      bg: 'rgba(37,99,235,0.12)',
    },
    {
      label: 'Patch Compliance',
      value: `${avgCompliance}%`,
      sub: `${fullyPatched} hosts fully patched`,
      icon: 'shield',
      color: '#0f766e',
      bg: 'rgba(20,184,166,0.12)',
    },
    {
      label: 'Critical Exposure',
      value: criticalCves,
      sub: `${highCves} additional high CVEs`,
      icon: 'bug',
      color: '#dc2626',
      bg: 'rgba(239,68,68,0.12)',
    },
    {
      label: 'Reboot Queue',
      value: rebootRequired,
      sub: 'pending restart to complete patching',
      icon: 'refresh',
      color: '#b45309',
      bg: 'rgba(245,158,11,0.14)',
    },
    {
      label: 'Patch Backlog',
      value: totalUpgradable,
      sub: 'remaining package updates',
      icon: 'package',
      color: '#06b6d4',
      bg: 'rgba(139,92,246,0.12)',
    },
    {
      label: '30-Day Success',
      value: `${successRate}%`,
      sub: `${jobsSuccess} successful / ${jobsFailed} failed`,
      icon: 'timeline',
      color: '#0f766e',
      bg: 'rgba(16,185,129,0.12)',
    },
  ];

  const priorityItems = [
    {
      label: 'Hosts below target',
      detail: `${needsAttention} host${needsAttention === 1 ? '' : 's'} need remediation to get back above 80% compliance.`,
      tone: needsAttention > 0 ? '#dc2626' : '#16a34a',
      bg: needsAttention > 0 ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)',
    },
    {
      label: 'Restart backlog',
      detail: `${rebootRequired} host${rebootRequired === 1 ? '' : 's'} still need a reboot to finalize updates.`,
      tone: rebootRequired > 0 ? '#d97706' : '#16a34a',
      bg: rebootRequired > 0 ? 'rgba(245,158,11,0.14)' : 'rgba(34,197,94,0.12)',
    },
    {
      label: 'Patch execution quality',
      detail: jobTotal ? `${jobsSuccess} successful and ${jobsFailed} failed jobs were recorded in the last 30 days.` : 'No recent patch execution data has been recorded yet.',
      tone: jobsFailed > 0 ? '#b45309' : '#1d4ed8',
      bg: jobsFailed > 0 ? 'rgba(245,158,11,0.14)' : 'rgba(37,99,235,0.12)',
    },
  ];

  const groupHealth = useMemo(() => [...byGroup].sort((a, b) => {
    if (a.avg_compliance !== b.avg_compliance) return a.avg_compliance - b.avg_compliance;
    return b.total_cves - a.total_cves;
  }), [byGroup]);

  const riskiestGroup = groupHealth[0] || null;

  const riskiestHosts = useMemo(() => [...hostDetail].sort((a, b) => {
    if ((a.compliance_score || 0) !== (b.compliance_score || 0)) return (a.compliance_score || 0) - (b.compliance_score || 0);
    if ((b.cve_count || 0) !== (a.cve_count || 0)) return (b.cve_count || 0) - (a.cve_count || 0);
    return (b.upgradable_count || 0) - (a.upgradable_count || 0);
  }).slice(0, 5), [hostDetail]);

  const filteredHosts = useMemo(() => {
    const q = hostQuery.trim().toLowerCase();
    return hostDetail.filter(h => {
      const matchesQuery = !q || [h.hostname, h.ip, h.os, ...(h.groups || [])].join(' ').toLowerCase().includes(q);
      if (!matchesQuery) return false;
      if (hostFilter === 'attention') return (h.compliance_score || 0) < 80;
      if (hostFilter === 'offline') return !h.is_online;
      if (hostFilter === 'reboot') return !!h.reboot_required;
      if (hostFilter === 'backlog') return (h.upgradable_count || 0) > 0;
      return true;
    });
  }, [hostDetail, hostQuery, hostFilter]);

  const scoreBadgeClass = (score) => score >= 90 ? 'badge-success' : score >= 80 ? 'badge-warning' : 'badge-danger';

  return (
    <div className="compliance-shell">
      <div className="compliance-toolbar">
        <div className="compliance-tabs">
          <button className={`compliance-tab ${view==='overview'?'active':''}`} onClick={()=>setView('overview')}>Overview</button>
          <button className={`compliance-tab ${view==='groups'?'active':''}`} onClick={()=>setView('groups')}>By Group</button>
          <button className={`compliance-tab ${view==='hosts'?'active':''}`} onClick={()=>setView('hosts')}>By Host</button>
        </div>
        <button className="btn btn-sm" onClick={refreshCompliance}>{loading ? 'Refreshing...' : 'Refresh Data'}</button>
      </div>

      {loading && !overview && (
        <div className="card" style={{ textAlign: 'center', padding: '3rem' }}>
          <p style={{ color: '#64748b' }}>Loading compliance posture...</p>
        </div>
      )}

      {view==='overview' && overview && (
        <div className="compliance-stack">
          <div className="compliance-hero">
            <div className="compliance-hero-main">
              <div className="compliance-kicker">Fleet Compliance Posture</div>
              <div className="compliance-hero-score">
                <div className="compliance-score-ring" style={{ color: posture.tone, background: posture.bg, borderColor: posture.border }}>
                  <span>{avgCompliance}%</span>
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: 28, color: '#0f172a' }}>{posture.title}</h3>
                  <p style={{ margin: '8px 0 0', color: '#475569', fontSize: 14, lineHeight: 1.7 }}>
                    {posture.description}
                  </p>
                </div>
              </div>
              <div className="compliance-chip-row">
                <span className="compliance-chip">Coverage {coveragePct}%</span>
                <span className="compliance-chip">Fully Patched {fullyPatched}</span>
                <span className="compliance-chip">Needs Attention {needsAttention}</span>
                <span className="compliance-chip">Critical CVEs {criticalCves}</span>
              </div>
            </div>
            <div className="compliance-hero-side">
              <div className="compliance-side-label">Compliance Notes</div>
              <div className="compliance-side-metric">
                <strong>{totalHosts}</strong>
                <span>Total managed hosts</span>
              </div>
              <div className="compliance-side-metric">
                <strong>{jobsSuccess}</strong>
                <span>Successful patch jobs in the last 30 days</span>
              </div>
              <div className="compliance-side-metric">
                <strong>{rebootRequired}</strong>
                <span>Hosts still waiting for restart</span>
              </div>
            </div>
          </div>

          <div className="compliance-summary-grid">
            {summaryCards.map(card => (
              <div key={card.label} className="compliance-summary-card">
                <div className="compliance-summary-head">
                  <span className="compliance-summary-icon" style={{ color: card.color, background: card.bg }}>
                    <AppIcon name={card.icon} size={18} />
                  </span>
                  <span className="compliance-summary-label">{card.label}</span>
                </div>
                <div className="compliance-summary-value">{card.value}</div>
                <div className="compliance-summary-sub">{card.sub}</div>
              </div>
            ))}
          </div>

          <div className="grid-2">
            <div className="card compliance-panel">
              <div className="card-header">
                <h3>Compliance Distribution</h3>
                <span className="badge badge-info">{totalHosts} hosts</span>
              </div>
              <div className="compliance-distribution">
                {distributionRows.map(row => (
                  <div key={row.key} className="distribution-row">
                    <div className="distribution-copy">
                      <strong>{row.label}</strong>
                      <span>{row.hint}</span>
                    </div>
                    <div className="distribution-bar">
                      <div className="distribution-fill" style={{ width: `${row.percent}%`, background: row.color }} />
                    </div>
                    <div className="distribution-meta">
                      <strong>{row.count}</strong>
                      <span>{row.percent}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card compliance-panel">
              <div className="card-header">
                <h3>Operational Priorities</h3>
                <span className="badge badge-warning">Review daily</span>
              </div>
              <div className="priority-list">
                {priorityItems.map(item => (
                  <div key={item.label} className="priority-item">
                    <span className="priority-dot" style={{ background: item.bg, color: item.tone }} />
                    <div>
                      <strong>{item.label}</strong>
                      <p>{item.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid-2">
            <div className="card compliance-panel">
              <div className="card-header">
                <h3>Group Risk Spotlight</h3>
                <button className="btn btn-sm btn-secondary" onClick={() => setView('groups')}>Open Groups</button>
              </div>
              {riskiestGroup ? (
                <div className="spotlight-card">
                  <div className="spotlight-top">
                    <div>
                      <div className="spotlight-kicker">Lowest-performing group</div>
                      <h4>{riskiestGroup.group}</h4>
                    </div>
                    <span className={`badge ${scoreBadgeClass(riskiestGroup.avg_compliance)}`}>{riskiestGroup.avg_compliance}% avg</span>
                  </div>
                  <div className="spotlight-grid">
                    <div><span>Hosts</span><strong>{riskiestGroup.host_count}</strong></div>
                    <div><span>Online</span><strong>{riskiestGroup.online}</strong></div>
                    <div><span>Total CVEs</span><strong>{riskiestGroup.total_cves}</strong></div>
                    <div><span>Upgradable</span><strong>{riskiestGroup.total_upgradable}</strong></div>
                  </div>
                </div>
              ) : (
                <p className="text-muted">No grouped compliance data is available yet.</p>
              )}
            </div>

            <div className="card compliance-panel">
              <div className="card-header">
                <h3>Hosts Requiring Review</h3>
                <button className="btn btn-sm btn-secondary" onClick={() => setView('hosts')}>Open Host List</button>
              </div>
              {!riskiestHosts.length ? (
                <p className="text-muted">No host-level compliance data is available yet.</p>
              ) : (
                <div className="review-host-list">
                  {riskiestHosts.map(host => (
                    <div key={host.id} className="review-host-item">
                      <div>
                        <strong>{host.hostname}</strong>
                        <span>{host.ip} - {(host.groups || []).join(', ') || 'Ungrouped'}</span>
                      </div>
                      <div className="review-host-metrics">
                        <span className={`badge ${scoreBadgeClass(host.compliance_score || 0)}`}>{host.compliance_score || 0}%</span>
                        <span className="badge badge-info">{host.upgradable_count || 0} pkgs</span>
                        {host.reboot_required && <span className="badge badge-warning">Reboot</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {view==='groups' && (
        <div className="compliance-stack">
          <div className="card compliance-panel">
            <div className="card-header">
              <h3>Compliance by Group</h3>
              <span className="badge badge-info">{byGroup.length} group{byGroup.length === 1 ? '' : 's'}</span>
            </div>
            {byGroup.length===0 ? <p className="text-muted">No groups with hosts found.</p> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Group</th><th>Hosts</th><th>Online</th><th>Avg Compliance</th><th>Lowest Score</th><th>Total CVEs</th><th>Upgradable</th></tr></thead>
                  <tbody>{groupHealth.map((g,i)=><tr key={i}><td><strong>{g.group}</strong></td><td>{g.host_count}</td><td>{g.online}</td><td><span className={`badge ${scoreBadgeClass(g.avg_compliance)}`}>{g.avg_compliance}%</span></td><td>{g.min_compliance}%</td><td>{g.total_cves}</td><td>{g.total_upgradable}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
      {view==='hosts' && (
        <div className="card compliance-panel">
          <div className="card-header">
            <h3>Per-Host Compliance</h3>
            <span className="badge badge-info">{filteredHosts.length} host{filteredHosts.length === 1 ? '' : 's'}</span>
          </div>
          <div className="compliance-table-toolbar">
            <input className="input search-input" placeholder="Search by host, IP, OS, or group..." value={hostQuery} onChange={e => setHostQuery(e.target.value)} />
            <div className="compliance-filter-pills">
              {[
                ['all', 'All Hosts'],
                ['attention', 'Needs Attention'],
                ['offline', 'Offline'],
                ['reboot', 'Reboot Queue'],
                ['backlog', 'Patch Backlog'],
              ].map(([key, label]) => (
                <button key={key} className={`compliance-pill ${hostFilter === key ? 'active' : ''}`} onClick={() => handleHostFilterChange(key)}>{label}</button>
              ))}
              {hostFilter !== 'all' && (
                <button className="compliance-pill" onClick={() => handleHostFilterChange('all')}>Clear</button>
              )}
            </div>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Hostname</th><th>IP</th><th>OS</th><th>Status</th><th>Compliance</th><th>CVEs</th><th>Upgradable</th><th>Reboot</th><th>Groups</th><th>Last Patched</th></tr></thead>
              <tbody>{filteredHosts.map(h=><tr key={h.id}><td><strong>{h.hostname}</strong></td><td>{h.ip}</td><td>{h.os}</td><td>{h.is_online?<span className="badge badge-success">Online</span>:<span className="badge badge-danger">Offline</span>}</td><td><span className={`badge ${scoreBadgeClass(h.compliance_score)}`}>{h.compliance_score}%</span></td><td>{h.cve_count}</td><td>{h.upgradable_count}</td><td>{h.reboot_required?<span className="badge badge-warning">Yes</span>:<span className="badge badge-info">No</span>}</td><td>{(h.groups||[]).join(', ') || 'Ungrouped'}</td><td>{h.last_patched ? new Date(h.last_patched).toLocaleDateString() : 'Not recorded'}</td></tr>)}</tbody>
            </table>
          </div>
          {!filteredHosts.length && <p className="text-muted" style={{ marginTop: 12 }}>No hosts match the current compliance filter.</p>}
        </div>
      )}
    </div>
  );
}
