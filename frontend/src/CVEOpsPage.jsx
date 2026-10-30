import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './OpsPages.css';

// Debounce hook for search input to improve performance on large datasets
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const handler = setTimeout(() => {
      if (mountedRef.current) {
        setDebouncedValue(value);
      }
    }, delay);
    return () => {
      mountedRef.current = false;
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

// Local storage persistence hook for filter state (UI-009: Filter Persistence)
function useFilterPersistence(key) {
  const [savedFilters, setSavedFilters] = useState({});

  useEffect(() => {
    try {
      const saved = localStorage.getItem(`pm-filters-${key}`);
      if (saved) {
        setSavedFilters(JSON.parse(saved));
      }
    } catch {}
  }, [key]);

  const saveFilters = useCallback((filters) => {
    try {
      localStorage.setItem(`pm-filters-${key}`, JSON.stringify(filters));
    } catch {}
  }, [key]);

  return [savedFilters, saveFilters];
}

export default function CVEOpsPage({ API, apiFetch, hasRole, getToken, AppIcon }) {
  const [cves, setCves] = useState([]);
  const [stats, setStats] = useState(null);
  
  // Persist filters to localStorage (UI-009)
  const [persistedFilters, setPersistedFilters] = useFilterPersistence('cve');
  
  // Persist pagination state to localStorage (UI-010)
  const [page, setPage] = useState(() => {
    try {
      const saved = localStorage.getItem('pm_cve_page');
      return saved ? parseInt(saved, 10) : 1;
    } catch { return 1; }
  });
  
  // Save page to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem('pm_cve_page', String(page));
    } catch {}
  }, [page]);
  
  const [search, setSearch] = useState(persistedFilters.search || '');
  // Debounce search input by 300ms to avoid excessive API calls
  const debouncedSearch = useDebounce(search, 300);
  const [severity, setSeverity] = useState(persistedFilters.severity || '');
  const [onlyWithHosts, setOnlyWithHosts] = useState(persistedFilters.onlyWithHosts || false);
  const [form, setForm] = useState({ cve_id: '', description: '', severity: 'medium', cvss_score: '', affected_packages: '', advisory_url: '' });
  const [toast, setToast] = useState(null);
  const [nvdDays, setNvdDays] = useState(2);
  const [syncSource, setSyncSource] = useState('nvd');
  const [importing, setImporting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [selectedCve, setSelectedCve] = useState(null);
  const [cveDetail, setCveDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [perPage] = useState(50);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const fileInputRef = useRef(null);

  const refresh = useCallback(() => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(perPage));
    if (severity) params.set('severity', severity);
    if (search) params.set('search', search);
    if (onlyWithHosts) params.set('include_hosts_only', 'true');
    
    apiFetch(`${API}/api/cve/?${params}`).then(r => r.json()).then(data => {
      // Backend returns paginated response: {items, total, page, per_page, pages}
      if (data && Array.isArray(data.items)) {
        setCves(data.items);
        setTotal(data.total || 0);
        setPages(data.pages || 1);
      } else if (Array.isArray(data)) {
        // Fallback for non-paginated response
        setCves(data);
        setTotal(data.length);
        setPages(1);
      } else {
        setCves([]);
        setTotal(0);
        setPages(1);
      }
    }).catch(() => {
      setCves([]);
      setTotal(0);
      setPages(1);
    });
    apiFetch(`${API}/api/cve/stats`).then(r => r.json()).then(setStats).catch(() => {});
  }, [API, apiFetch, severity, search, onlyWithHosts, page, perPage]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Persist filters to localStorage when they change (UI-009: Filter Persistence)
  useEffect(() => {
    setPersistedFilters({ search: debouncedSearch, severity, onlyWithHosts });
  }, [debouncedSearch, severity, onlyWithHosts, setPersistedFilters]);

  // Keyboard navigation support (UI-014: Keyboard Nav)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl/Cmd + F focuses search
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-input')?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const showToast = (text, type = 'info') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3000);
  };

  const create = () => {
    if (!form.cve_id) return showToast('CVE ID required', 'danger');
    const body = {
      ...form,
      cvss_score: form.cvss_score ? parseFloat(form.cvss_score) : null,
      affected_packages: form.affected_packages ? form.affected_packages.split(',').map(item => item.trim()).filter(Boolean) : [],
    };
    apiFetch(`${API}/api/cve/`, { method: 'POST', body: JSON.stringify(body) })
      .then(r => { if (!r.ok) throw new Error('Failed to add'); return r; })
      .then(() => {
        refresh();
        setForm({ cve_id: '', description: '', severity: 'medium', cvss_score: '', affected_packages: '', advisory_url: '' });
        showToast('CVE added', 'success');
      })
      .catch(e => showToast(e.message, 'danger'));
  };

  const del = (id) => {
    if (!window.confirm('Delete CVE?')) return;
    apiFetch(`${API}/api/cve/${id}`, { method: 'DELETE' }).then(() => {
      refresh();
      showToast('CVE deleted', 'success');
    });
  };

  const triggerImport = () => fileInputRef.current?.click();

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await apiFetch(`${API}/api/cve/import`, { method: 'POST', body: fd });
      if (!r.ok) {
        const d = await r.json().catch(() => ({ error: 'Import failed' }));
        throw new Error(d.error || 'Import failed');
      }
      const d = await r.json();
      refresh();
      showToast(`Import completed. Added ${d.created}, updated ${d.updated}, host links ${d.host_links || 0}`, 'success');
    } catch (err) {
      showToast(err.message, 'danger');
    } finally {
      setImporting(false);
      e.target.value = '';
    }
  };

  const syncFeed = async () => {
    setSyncing(true);
    try {
      const runSync = async (credentials = null) => {
        const params = new URLSearchParams();
        params.set('source', syncSource);
        if (syncSource === 'nvd') params.set('days', String(nvdDays || 2));
        const options = { method: 'POST' };
        if (syncSource === 'cis' && credentials) {
          options.headers = { 'Content-Type': 'application/json' };
          options.body = JSON.stringify(credentials);
        }
        const response = await apiFetch(`${API}/api/cve/sync?${params.toString()}`, options);
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ error: 'Sync failed' }));
          const detail = payload?.detail && typeof payload.detail === 'object' ? payload.detail : null;
          const errorCode = detail?.code || payload?.code || '';
          const errorText = detail?.error || payload?.error || 'Sync failed';
          if (syncSource === 'cis' && response.status === 401 && errorCode === 'cis_credentials_required' && !credentials) {
            const username = window.prompt('CIS username required for this feed:');
            if (!username) throw new Error('CIS sync canceled');
            const password = window.prompt('CIS password:');
            if (!password) throw new Error('CIS sync canceled');
            return runSync({ cis_username: username, cis_password: password });
          }
          throw new Error(errorText);
        }
        return response.json();
      }
      const d = await runSync();
      refresh();
      if (syncSource === 'cis') {
        showToast(`Fetched ${d.fetched} CVEs from CIS. Enriched ${d.enriched || 0}. Added ${d.created}, updated ${d.updated}.`, 'success');
      } else {
        showToast(`Fetched ${d.fetched} CVEs (${d.start} to ${d.end})`, 'success');
      }
    } catch (err) {
      showToast(err.message, 'danger');
    } finally {
      setSyncing(false);
    }
  };

  const openDetail = async (cveId) => {
    setSelectedCve(cveId);
    setLoadingDetail(true);
    try {
      const r = await apiFetch(`${API}/api/cve/${cveId}`);
      const d = await r.json();
      setCveDetail(d);
    } catch (err) {
      setCveDetail({ error: err.message || 'Failed to load CVE details' });
    }
    setLoadingDetail(false);
  };

  const safeStats = stats || {
    total_cves: 0,
    by_severity: { critical: 0, high: 0, medium: 0, low: 0 },
    open_vulnerabilities: 0,
    patched_vulnerabilities: 0,
  };

  // Ensure cves is always an array
  const safeCves = Array.isArray(cves) ? cves : [];

  const totalTracked = safeStats.total_cves || 0;
  const criticalCount = safeStats.by_severity?.critical || 0;
  const highCount = safeStats.by_severity?.high || 0;
  const mediumCount = safeStats.by_severity?.medium || 0;
  const lowCount = safeStats.by_severity?.low || 0;
  const openCount = safeStats.open_vulnerabilities || 0;
  const patchedCount = safeStats.patched_vulnerabilities || 0;
  const linkedRecords = safeCves.filter(cve => Number(cve.affected_hosts || 0) > 0).length;
  const closureRate = openCount + patchedCount ? Math.round((patchedCount / (openCount + patchedCount)) * 100) : 0;

  const posture = criticalCount > 0
    ? {
        title: 'Immediate exposure requires action',
        description: 'Critical vulnerabilities are present. Prioritize host-linked records and queue remediation jobs quickly.',
        tone: '#b91c1c',
        bg: 'linear-gradient(145deg, #fef2f2, var(--card-bg)6f6)',
        border: '#fca5a5',
      }
    : highCount > 0
      ? {
          title: 'Elevated risk posture',
          description: 'High-severity CVEs remain open. Review affected hosts and convert findings into patch work quickly.',
          tone: '#b45309',
          bg: 'linear-gradient(145deg, var(--card-bg)beb, var(--card-bg)df5)',
          border: '#fcd34d',
        }
      : {
          title: 'Threat posture is under control',
          description: 'Critical and high severity exposure is limited. Keep feeds fresh and continue normal remediation cadence.',
          tone: '#166534',
          bg: 'linear-gradient(145deg, #ecfdf3, #f8fffb)',
          border: '#86efac',
        };

  const summaryCards = [
    { label: 'Tracked CVEs', value: totalTracked, sub: `${safeCves.length} in the current view`, icon: 'database', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
    { label: 'Critical', value: criticalCount, sub: 'highest-severity findings', icon: 'bug', color: '#dc2626', bg: 'rgba(239,68,68,0.12)' },
    { label: 'High Severity', value: highCount, sub: `${mediumCount} medium and ${lowCount} low`, icon: 'shield', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
    { label: 'Open Vulnerabilities', value: openCount, sub: 'still awaiting remediation', icon: 'list', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
    { label: 'Patched', value: patchedCount, sub: `${closureRate}% closure rate`, icon: 'refresh', color: '#0f766e', bg: 'rgba(16,185,129,0.12)' },
    { label: 'Host-linked Records', value: linkedRecords, sub: onlyWithHosts ? 'host-linked filter enabled' : 'records currently tied to hosts', icon: 'server', color: '#1d4ed8', bg: 'rgba(59,130,246,0.12)' },
  ];

  const analystPriorities = [
    { label: 'Critical backlog', detail: `${criticalCount} critical CVEs require immediate validation or remediation.` },
    { label: 'Open remediation load', detail: `${openCount} vulnerabilities remain open across tracked records.` },
    { label: 'Feed freshness', detail: syncSource === 'nvd' ? `NVD sync window is currently ${nvdDays} day(s). Import vendor spreadsheets when needed.` : 'CIS feed mode is selected. Fetch uses the default CIS advisories source automatically.' },
  ];

  return (
    <div className="ops-shell">
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: 20,
          right: 20,
          padding: '12px 16px',
          borderRadius: 8,
          background: toast.type === 'success' ? '#0f5132' : toast.type === 'danger' ? '#842029' : '#1e293b',
          color: 'var(--card-bg)',
          boxShadow: '0 10px 20px rgba(0,0,0,0.25)',
          zIndex: 2000,
        }}>
          {toast.text}
        </div>
      )}

      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: posture.border, background: posture.bg }}>
          <div className="ops-kicker">Threat exposure</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Response focus</span>
              <span className="ops-emphasis-value" style={{ color: posture.tone }}>{criticalCount > 0 ? criticalCount : `${closureRate}%`}</span>
              <span className="ops-emphasis-meta">{criticalCount > 0 ? 'critical items' : 'closure rate'}</span>
            </div>
            <div className="ops-hero-copy">
              <h3>{posture.title}</h3>
              <p>{posture.description}</p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">{totalTracked} tracked CVEs</span>
            <span className="ops-chip">{openCount} open remediation items</span>
            <span className="ops-chip">{onlyWithHosts ? 'Showing host-linked findings only' : 'Showing all matching findings'}</span>
            <span className="ops-chip">NVD window: {nvdDays} day(s)</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Analyst priorities</span>
          <div className="ops-side-metric">{criticalCount + highCount}</div>
          <p className="ops-side-note">Critical and high-severity findings should be triaged first, especially when they are already linked to hosts.</p>
          <div className="ops-list">
            {analystPriorities.map(item => (
              <div key={item.label} className="ops-list-item" style={{ padding: 0, borderBottom: 'none' }}>
                <div className="ops-list-copy">
                  <strong>{item.label}</strong>
                  <span>{item.detail}</span>
                </div>
                <span className="ops-chip">Focus</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {summaryCards.map(card => (
          <div key={card.label} className="ops-summary-card">
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

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Feed operations</div>
            <p className="ops-subtle">Keep threat intelligence current with NVD syncs, spreadsheet imports, and CSV exports for stakeholder reporting.</p>
          </div>
          <div className="ops-actions">
            {hasRole('admin', 'operator') && (
              <>
                <div className="form-row">
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Source</label>
                  <select className="input" value={syncSource} onChange={e => setSyncSource(e.target.value)} style={{ width: 130 }}>
                    <option value="nvd">NVD</option>
                    <option value="cis">CIS</option>
                  </select>
                </div>
                <div className="form-row">
                  <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Days</label>
                  <input className="input" type="number" min={1} max={30} value={nvdDays} onChange={e => setNvdDays(parseInt(e.target.value || '2', 10))} style={{ width: 84 }} disabled={syncSource !== 'nvd'} />
                </div>
                <button className="btn" onClick={syncFeed} disabled={syncing}>{syncing ? 'Syncing...' : 'Fetch Latest'}</button>
                <button className="btn" onClick={triggerImport} disabled={importing}>{importing ? 'Importing...' : 'Import CSV / XLSX'}</button>
                <input type="file" ref={fileInputRef} accept=".csv,.xls,.xlsx,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" style={{ display: 'none' }} onChange={handleImport} />
              </>
            )}
            <button
              className="btn btn-primary"
              onClick={async () => {
                try {
                  const r = await apiFetch(`${API}/api/cve/export`);
                  if (!r.ok) throw new Error(`Export failed (${r.status})`);
                  const blob = await r.blob();
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `cve_report_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.csv`;
                  a.click();
                  window.URL.revokeObjectURL(url);
                } catch (e) {
                  showToast(e.message || 'Export failed', 'danger');
                }
              }}
            >
              Export Report
            </button>
          </div>
        </div>
      </div>

      {hasRole('admin', 'operator') && (
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Register a CVE manually</div>
              <p className="ops-subtle">Use this when you need to seed internal advisories or vendor findings before the next feed sync.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <input className="input" placeholder="CVE-2026-XXXX" value={form.cve_id} onChange={e => setForm(current => ({ ...current, cve_id: e.target.value }))} />
            <select className="input" value={form.severity} onChange={e => setForm(current => ({ ...current, severity: e.target.value }))}>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <input className="input" placeholder="CVSS" value={form.cvss_score} onChange={e => setForm(current => ({ ...current, cvss_score: e.target.value }))} />
            <input className="input" placeholder="Affected packages (comma-separated)" value={form.affected_packages} onChange={e => setForm(current => ({ ...current, affected_packages: e.target.value }))} style={{ gridColumn: 'span 2' }} />
            <input className="input" placeholder="Advisory URL" value={form.advisory_url} onChange={e => setForm(current => ({ ...current, advisory_url: e.target.value }))} style={{ gridColumn: 'span 2' }} />
            <input className="input" placeholder="Description" value={form.description} onChange={e => setForm(current => ({ ...current, description: e.target.value }))} style={{ gridColumn: '1 / -1' }} />
          </div>
          <div style={{ marginTop: 14 }}>
            <button className="btn btn-primary" onClick={create}>Add CVE</button>
          </div>
        </div>
      )}

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">CVE inventory</div>
            <p className="ops-subtle">Filter by severity, keyword, or host linkage to drive remediation planning and export-ready reporting.</p>
          </div>
        </div>
        <div className="ops-table-toolbar">
          <div className="ops-pills" role="group" aria-label="Filter by severity">
            {[
              { key: '', label: 'All severities' },
              { key: 'critical', label: 'Critical' },
              { key: 'high', label: 'High' },
              { key: 'medium', label: 'Medium' },
              { key: 'low', label: 'Low' },
            ].map(filter => (
              <button 
                key={filter.label} 
                className={`ops-pill ${severity === filter.key ? 'active' : ''}`} 
                onClick={() => setSeverity(filter.key)}
                aria-pressed={severity === filter.key}
              >{filter.label}</button>
            ))}
          </div>
          <div className="form-row">
            <input className="input search-input" placeholder="Search CVE ID or description" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search CVEs by ID or description" />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              <input type="checkbox" checked={onlyWithHosts} onChange={e => setOnlyWithHosts(e.target.checked)} />
              Host-linked only
            </label>
          </div>
        </div>

        {safeCves.length === 0 ? (
          <div className="ops-empty">No CVEs match the current filters.</div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table ops-table" role="table" aria-label="CVE inventory">
                <thead>
                  <tr role="row">
                    <th role="columnheader">CVE ID</th>
                    <th role="columnheader">Severity</th>
                    <th role="columnheader">CVSS</th>
                    <th role="columnheader">Affected Hosts</th>
                    <th role="columnheader">Patched Hosts</th>
                    <th role="columnheader">Description</th>
                    <th role="columnheader">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {safeCves.map(cve => (
                    <tr key={cve.id} role="row">
                      <td>
                        <button className="link-btn" onClick={() => openDetail(cve.cve_id)} style={{ background: 'none', border: 'none', color: '#2563eb', cursor: 'pointer', fontWeight: 700 }} aria-label={`View details for ${cve.cve_id}`}>{cve.cve_id}</button>
                        <span className="ops-table-meta">{Number(cve.affected_hosts || 0) > 0 ? 'Linked to hosts' : 'Not yet linked to hosts'}</span>
                      </td>
                      <td><span className={`badge badge-${cve.severity === 'critical' ? 'danger' : cve.severity === 'high' ? 'warning' : cve.severity === 'medium' ? 'info' : 'success'}`}>{cve.severity}</span></td>
                      <td>{cve.cvss_score || 'N/A'}</td>
                      <td>{cve.affected_hosts}</td>
                      <td>{cve.patched_hosts}</td>
                      <td style={{ maxWidth: 320 }}>{cve.description || 'No description provided.'}</td>
                      <td>{hasRole('admin') && <button className="btn btn-sm btn-danger" onClick={() => del(cve.id)} aria-label={`Delete ${cve.cve_id}`}>Delete</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Pagination controls */}
            {pages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, padding: '16px 0', borderTop: '1px solid var(--border-color)' }}>
                <button 
                  className="btn btn-sm" 
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </button>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  Page {page} of {pages} ({total} total CVEs)
                </span>
                <button 
                  className="btn btn-sm" 
                  onClick={() => setPage(p => Math.min(pages, p + 1))}
                  disabled={page === pages}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {selectedCve && (
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">CVE details</div>
              <p className="ops-subtle">{selectedCve}</p>
            </div>
            <button className="btn btn-sm" onClick={() => { setSelectedCve(null); setCveDetail(null); }}>Close</button>
          </div>
          {loadingDetail ? (
            <div className="ops-empty">Loading CVE details...</div>
          ) : cveDetail?.error ? (
            <p className="text-danger">{cveDetail.error}</p>
          ) : cveDetail ? (
            <>
              <div className="ops-detail-grid">
                <div className="ops-detail-item"><span>Severity</span><strong>{cveDetail.severity || 'Unknown'}</strong></div>
                <div className="ops-detail-item"><span>CVSS</span><strong>{cveDetail.cvss_score || 'N/A'}</strong></div>
                <div className="ops-detail-item" style={{ gridColumn: '1 / -1' }}><span>Description</span><strong>{cveDetail.description || 'No description available.'}</strong></div>
              </div>
              <p className="ops-subtle" style={{ marginBottom: 12 }}>Remediation guidance: create a patch job for affected hosts or follow the linked advisory instructions from your vendor feed.</p>
              <div className="ops-panel" style={{ padding: 18, marginBottom: 0 }}>
                <div className="ops-panel-title" style={{ marginBottom: 12 }}>Affected hosts ({cveDetail.affected_hosts?.length || 0})</div>
                {(!cveDetail.affected_hosts || cveDetail.affected_hosts.length === 0) ? (
                  <div className="ops-empty">No hosts linked to this CVE yet.</div>
                ) : (
                  <div className="ops-list">
                    {cveDetail.affected_hosts.map(host => (
                      <div key={host.host_id} className="ops-list-item">
                        <div className="ops-list-copy">
                          <strong>{host.hostname}</strong>
                          <span>{host.ip}</span>
                        </div>
                        <div className="ops-list-metrics">
                          <span className={`badge badge-${host.status === 'patched' ? 'success' : host.status === 'affected' ? 'danger' : 'warning'}`}>{host.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
