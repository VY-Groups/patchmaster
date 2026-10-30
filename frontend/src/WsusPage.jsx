import React, { useState, useEffect, useCallback, useMemo } from 'react';

export function WsusPage({ hosts, API, apiFetch, useInterval, hasPerm }) {
  const windowsFeatureEnabled = hasPerm('windows_patching') || hasPerm('wsus');
  const windowsHosts = hosts.filter(h => ((h.os || '').toLowerCase().includes('windows')) || ((h.groups || []).map(g => (g || '').toLowerCase()).includes('windows')));
  const [selectedHost, setSelectedHost] = useState('');
  const [updates, setUpdates] = useState([]);
  const [selected, setSelected] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [msg, setMsg] = useState('');
  const [wsusPolicy, setWsusPolicy] = useState('latest');
  const [approvalDays, setApprovalDays] = useState(14);
  const [autoSnapshot, setAutoSnapshot] = useState(true);
  const [snapshotNamePrefix, setSnapshotNamePrefix] = useState('wsus-prepatch');
  const [filters, setFilters] = useState({ search:'', severity:'all', reboot:'all', downloaded:'all', sort:'title_asc' });
  const [excludeUpdates, setExcludeUpdates] = useState('');
  const [historyRows, setHistoryRows] = useState([]);
  const excludeTerms = useMemo(
    () => excludeUpdates.split(',').map(s => s.trim().toLowerCase()).filter(Boolean),
    [excludeUpdates]
  );
  const isWsusExcluded = useCallback((u) => {
    if (!excludeTerms.length) return false;
    const title = String(u?.Title || '').toLowerCase();
    const kb = String(u?.KBArticleIDs || '').toLowerCase();
    const id = String(u?.UpdateID || '').toLowerCase();
    return excludeTerms.some(t => title.includes(t) || kb.includes(t) || id.includes(t));
  }, [excludeTerms]);

  const filteredUpdates = React.useMemo(() => {
    const s = (filters.search || '').toLowerCase();
    return updates
      .filter(u => {
        const matchSearch = !s || (u.Title||'').toLowerCase().includes(s) || (u.KBArticleIDs||'').toString().includes(filters.search);
        const matchSeverity = filters.severity==='all' || (u.MsrcSeverity||'').toLowerCase() === filters.severity.toLowerCase();
        const matchReboot = filters.reboot==='all' || (filters.reboot==='yes'?u.RebootRequired:!u.RebootRequired);
        const matchDl = filters.downloaded==='all' || (filters.downloaded==='yes'?u.IsDownloaded:!u.IsDownloaded);
        return matchSearch && matchSeverity && matchReboot && matchDl;
      })
      .sort((a,b)=>{
        switch(filters.sort){
          case 'title_desc': return (b.Title||'').localeCompare(a.Title||'');
          case 'severity_desc': return (b.MsrcSeverity||'').localeCompare(a.MsrcSeverity||'');
          case 'reboot_desc': return (b.RebootRequired===true) - (a.RebootRequired===true);
          default: return (a.Title||'').localeCompare(b.Title||'');
        }
      });
  }, [updates, filters]);

  const policyAnalyzedUpdates = React.useMemo(() => {
    if (wsusPolicy !== 'n_minus_1') {
      return filteredUpdates.map(u => {
        if (isWsusExcluded(u)) return { ...u, policyIncluded: false, policyReason: 'Excluded by hold/exclude list' };
        return { ...u, policyIncluded: true, policyReason: 'Included by Latest policy' };
      });
    }
    const days = Math.max(0, Number(approvalDays) || 0);
    const cutoff = Date.now() - (days * 24 * 60 * 60 * 1000);
    return filteredUpdates.map(u => {
      const raw = u.LastDeploymentChangeTime || u.LastDeploymentChangeTimeUtc || '';
      const ts = Date.parse(raw);
      if (isWsusExcluded(u)) {
        return { ...u, policyIncluded: false, policyReason: 'Excluded by hold/exclude list' };
      }
      if (!Number.isFinite(ts)) {
        return { ...u, policyIncluded: false, policyReason: 'Excluded by N-1: release date unavailable' };
      }
      if (ts > cutoff) {
        return { ...u, policyIncluded: false, policyReason: `Excluded by N-1: newer than ${days} day approval window` };
      }
      return { ...u, policyIncluded: true, policyReason: 'Included by N-1 approval window' };
    });
  }, [filteredUpdates, wsusPolicy, approvalDays, isWsusExcluded]);
  const policyFilteredUpdates = policyAnalyzedUpdates.filter(u => u.policyIncluded);
  const policyExcludedUpdates = policyAnalyzedUpdates.filter(u => !u.policyIncluded);
  const wsusScopeRows = React.useMemo(() => {
    if (selected.length) {
      const selectedSet = new Set(selected.map(String));
      return policyFilteredUpdates.filter(u => selectedSet.has(String(u.UpdateID || '')));
    }
    return policyFilteredUpdates;
  }, [selected, policyFilteredUpdates]);
  const wsusSizeImpact = React.useMemo(() => {
    let totalBytes = 0;
    let known = 0;
    let unknown = 0;
    wsusScopeRows.forEach((u) => {
      const n = Number(u?.MaxDownloadSize);
      if (Number.isFinite(n) && n > 0) {
        totalBytes += n;
        known += 1;
      } else {
        unknown += 1;
      }
    });
    return { totalBytes, known, unknown, count: wsusScopeRows.length };
  }, [wsusScopeRows]);

  useInterval(() => {
    if (!selectedHost) return;
    apiFetch(`${API}/api/agent/${selectedHost}/wsus/status`).then(r=>r.json()).then(setStatus).catch(()=>{});
  }, 8000);
  const refreshHistory = useCallback(async () => {
    if (!selectedHost) { setHistoryRows([]); return; }
    const host = windowsHosts.find(h => h.ip === selectedHost);
    if (!host?.id) { setHistoryRows([]); return; }
    try {
      const r = await apiFetch(`${API}/api/jobs?host_id=${host.id}&limit=25`);
      const d = await r.json().catch(() => []);
      const rows = Array.isArray(d) ? d : [];
      const onlyPatch = rows.filter(j => ['server_patch','upgrade','offline_install','windows_update','patch'].includes(String(j.action || '').toLowerCase()));
      setHistoryRows(onlyPatch);
    } catch {
      setHistoryRows([]);
    }
  }, [selectedHost, windowsHosts]);
  useEffect(() => {
    if (selectedHost) refreshHistory();
  }, [selectedHost, refreshHistory]);

  const refreshUpdates = async () => {
    if (!selectedHost) return alert('Select a Windows host first.');
    setLoading(true);
    setMsg('');
    setSelected([]);
    try {
      const r = await apiFetch(`${API}/api/agent/${selectedHost}/wsus/updates`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Failed to fetch updates');
      setUpdates(d.updates || []);
      refreshHistory();
    } catch (e) {
      setMsg(e.message);
    }
    setLoading(false);
  };

  const downloadUpdatesOnly = async () => {
    if (!selectedHost) return alert('Select a Windows host first.');
    const selectedIds = (selected.length ? selected : policyFilteredUpdates.map(u => u.UpdateID).filter(Boolean))
      .filter(id => {
        const row = updates.find(u => String(u.UpdateID) === String(id));
        return row ? !isWsusExcluded(row) : true;
      });
    if (!selectedIds.length) return alert('No updates selected by filters/policy.');
    setMsg('');
    const r = await apiFetch(`${API}/api/agent/${selectedHost}/wsus/download`, { method:'POST', body: JSON.stringify({ update_ids: selectedIds }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok) {
      setMsg(`Download started for ${selectedIds.length} update(s). You can install later from downloaded filter.`);
      setTimeout(() => refreshUpdates(), 2500);
      return;
    }
    setMsg(d.error || d.detail || 'Failed to start download');
  };

  const installUpdates = async () => {
    if (!selectedHost) return alert('Select a Windows host first.');
    const selectedIds = (selected.length ? selected : policyFilteredUpdates.map(u => u.UpdateID).filter(Boolean))
      .filter(id => {
        const row = updates.find(u => String(u.UpdateID) === String(id));
        return row ? !isWsusExcluded(row) : true;
      });
    if (!window.confirm(`Install ${selectedIds.length} Windows update(s) on this host? Policy: ${wsusPolicy === 'n_minus_1' ? `N-1 (${approvalDays}d)` : 'Latest'}.`)) return;
    setMsg('');
    try {
      if (autoSnapshot) {
        const hostRow = windowsHosts.find(h => h.ip === selectedHost);
        if (!hostRow?.id) throw new Error('Cannot resolve Windows host for snapshot.');
        const snapName = `${snapshotNamePrefix || 'wsus-prepatch'}-${Date.now()}`;
        const s = await apiFetch(`${API}/api/agent/by-host/${hostRow.id}/snapshot/create`, {
          method:'POST',
          body: JSON.stringify({ name: snapName, mode: 'full_system' })
        });
        const sd = await s.json().catch(() => ({}));
        if (!s.ok || sd?.success === false) {
          throw new Error(sd?.error || `Snapshot failed (${s.status})`);
        }
      }
      const body = { update_ids: selectedIds };
      const r = await apiFetch(`${API}/api/agent/${selectedHost}/wsus/install`, { method:'POST', body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Failed to start install job');
      setMsg(`Install started for ${selectedIds.length} update(s). Monitor agent status below.${autoSnapshot ? ' Snapshot created before install.' : ''}`);
    } catch (e) {
      setMsg(e.message);
    }
  };

  if (!windowsFeatureEnabled) {
    return (
      <div className="card">
        <h3>Windows Update Channel</h3>
        <p className="text-muted">Windows patching is not enabled for the current license or role. Open the License page to verify whether Windows patching and WSUS support are included for this environment.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="card highlight-card">
        <h3>Windows Update Channel</h3>
        <p>Use Check Updates to scan the selected Windows host, review the policy-scoped results, then download or install them. This workflow uses the Windows Update Agent on the target host and does not require a separate WSUS server inside Patch-SecOps Solution.</p>
      </div>

      <div className="card">
        <div className="form-row">
          <select className="input" value={selectedHost} onChange={e=>{setSelectedHost(e.target.value); setUpdates([]);}}>
            <option value="">-- Select Windows Host --</option>
            {windowsHosts.map(h => <option key={h.id} value={h.ip}>{h.hostname} ({h.ip})</option>)}
          </select>
          <select className="input" value={wsusPolicy} onChange={e=>setWsusPolicy(e.target.value)} style={{maxWidth:230}}>
            <option value="latest">Policy: Latest approved updates</option>
            <option value="n_minus_1">Policy: N-1 stabilization window</option>
          </select>
          {wsusPolicy==='n_minus_1' && (
            <input
              className="input"
              type="number"
              min="0"
              value={approvalDays}
              onChange={e=>setApprovalDays(e.target.value)}
              style={{maxWidth:180}}
              placeholder="Age gate (days)"
            />
          )}
          <label className="toggle-option" style={{display:'inline-flex',alignItems:'center',gap:6}}>
            <input type="checkbox" checked={autoSnapshot} onChange={e=>setAutoSnapshot(e.target.checked)} />
            Auto-Snapshot
          </label>
          <input
            className="input"
            style={{maxWidth:260}}
            placeholder="Exclude updates (KB/title/id, comma-separated)"
            value={excludeUpdates}
            onChange={e=>setExcludeUpdates(e.target.value)}
          />
          {autoSnapshot && (
            <input className="input" style={{maxWidth:220}} placeholder="Snapshot prefix" value={snapshotNamePrefix} onChange={e=>setSnapshotNamePrefix(e.target.value)} />
          )}
          <button className="btn btn-primary" onClick={refreshUpdates} disabled={loading}>{loading?'Loading...':'Check Updates'}</button>
          <button className="btn btn-secondary" onClick={downloadUpdatesOnly} disabled={!selectedHost || (status && status.status==='installing')}>
            {selected.length ? `Download Selected (${selected.length})` : `Download In Policy Scope (${policyFilteredUpdates.length})`}
          </button>
          <button className="btn btn-warning" onClick={installUpdates} disabled={!selectedHost || (status && status.status==='installing')}>
            {selected.length ? `Install Selected (${selected.length})` : `Install In Policy Scope (${policyFilteredUpdates.length})`}
          </button>
        </div>
        {msg && <p style={{marginTop:10,fontWeight:500,color:msg.toLowerCase().includes('failed')||msg.toLowerCase().includes('error')?'#dc3545':'#28a745'}}>{msg}</p>}
        {status && (
          <div style={{marginTop:10,display:'flex',gap:10,flexWrap:'wrap'}}>
            <span className="badge badge-info">State: {status.status || 'idle'}</span>
            <span className="badge badge-success">Pending: {status.pending_count ?? 0}</span>
            {status.last_scan && <span className="badge badge-dark">Last scan: {new Date(status.last_scan).toLocaleTimeString()}</span>}
            {status.last_error && <span className="badge badge-danger">Error: {status.last_error}</span>}
          </div>
        )}
        <div style={{marginTop:10,display:'flex',gap:10,flexWrap:'wrap'}}>
          <span className="badge badge-info">Scope: {wsusSizeImpact.count} update(s)</span>
          <span className="badge badge-info">Estimated download: {(wsusSizeImpact.totalBytes / (1024 * 1024)).toFixed(2)} MB</span>
          <span className="badge badge-success">Known size: {wsusSizeImpact.known}</span>
          <span className="badge badge-warning">Unknown size: {wsusSizeImpact.unknown}</span>
        </div>
      </div>

      {selectedHost && (
        <div className="card">
          <h3>Windows Update Agent Status</h3>
          {status && Object.keys(status).length ? (
            <pre className="code-block">{JSON.stringify(status, null, 2)}</pre>
          ) : (
            <p className="text-muted">No agent status is available yet. Run Check Updates first to populate the Windows update scan state for this host.</p>
          )}
        </div>
      )}
      {selectedHost && (
        <div className="card">
          <h3>Patch History (Latest 25)</h3>
          {historyRows.length === 0 ? <p className="text-muted">No patch history yet for this host.</p> : (
            <table className="table">
              <thead><tr><th>ID</th><th>Action</th><th>Status</th><th>Started</th><th>Completed</th></tr></thead>
              <tbody>
                {historyRows.map(h => (
                  <tr key={`wsus-history-${h.id}`}>
                    <td>#{h.id}</td>
                    <td>{h.action}</td>
                    <td><span className={`badge ${String(h.status||'').toLowerCase()==='success'?'badge-success':String(h.status||'').toLowerCase()==='failed'?'badge-danger':String(h.status||'').toLowerCase()==='running'?'badge-info':'badge-warning'}`}>{h.status || '-'}</span></td>
                    <td>{h.started_at ? new Date(h.started_at).toLocaleString() : '-'}</td>
                    <td>{h.completed_at ? new Date(h.completed_at).toLocaleString() : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="card">
        <h3>Pending Updates ({policyFilteredUpdates.length}/{updates.length})</h3>
        {wsusPolicy==='n_minus_1' && (
          <p className="text-muted">N-1 policy keeps updates older than {approvalDays} day(s) using LastDeploymentChangeTime. Excluded by policy: {policyExcludedUpdates.length}.</p>
        )}
        <div className="form-row" style={{marginBottom:10}}>
          <input className="input" placeholder="Search title or KB..." value={filters.search} onChange={e=>setFilters({...filters, search:e.target.value})} />
          <select className="input" value={filters.severity} onChange={e=>setFilters({...filters, severity:e.target.value})}>
            <option value="all">All severities</option>
            <option value="Critical">Critical</option>
            <option value="Important">Important</option>
            <option value="Moderate">Moderate</option>
            <option value="Low">Low</option>
            <option value="Unspecified">Unspecified</option>
          </select>
          <select className="input" value={filters.reboot} onChange={e=>setFilters({...filters, reboot:e.target.value})}>
            <option value="all">Reboot: All</option>
            <option value="yes">Reboot required</option>
            <option value="no">No reboot</option>
          </select>
          <select className="input" value={filters.downloaded} onChange={e=>setFilters({...filters, downloaded:e.target.value})}>
            <option value="all">Downloaded: All</option>
            <option value="yes">Downloaded</option>
            <option value="no">Not downloaded</option>
          </select>
          <select className="input" value={filters.sort} onChange={e=>setFilters({...filters, sort:e.target.value})}>
            <option value="title_asc">Title A-Z</option>
            <option value="title_desc">Title Z-A</option>
            <option value="severity_desc">Severity high-low</option>
            <option value="reboot_desc">Reboot required first</option>
          </select>
          <button className="btn btn-sm btn-primary" onClick={() => setSelected(policyFilteredUpdates.map(u => u.UpdateID).filter(Boolean))}>Select All</button>
          <button className="btn btn-sm" onClick={() => setSelected([])}>Clear</button>
        </div>
        {policyFilteredUpdates.length === 0 ? <p className="text-muted">No updates returned (or filtered out by policy).</p> : (
          <table className="table">
            <thead><tr><th style={{width:'60px'}}>Select</th><th>Title</th><th>KB</th><th>Severity</th><th>Downloaded</th><th>Reboot</th><th>ID</th></tr></thead>
            <tbody>{policyFilteredUpdates.map((u,i)=>(
              <tr key={i} style={isWsusExcluded(u) ? {opacity:0.55} : undefined}>
                <td><input type="checkbox" checked={selected.includes(u.UpdateID)} onChange={()=>setSelected(prev=>prev.includes(u.UpdateID)?prev.filter(x=>x!==u.UpdateID):[...prev,u.UpdateID])} /></td>
                <td style={{maxWidth:520,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}} title={u.Title || ''}>{u.Title || '-'}</td>
                <td>{Array.isArray(u.KBArticleIDs) ? u.KBArticleIDs.join(',') : (u.KBArticleIDs || '-')}</td>
                <td>{u.MsrcSeverity || '-'}</td>
                <td>{u.IsDownloaded ? <span className="badge badge-success">Yes</span> : <span className="badge badge-warning">No</span>}</td>
                <td>{u.RebootRequired ? <span className="badge badge-warning">Yes</span> : <span className="badge badge-success">No</span>}</td>
                <td><code style={{fontSize:11}}>{u.UpdateID || '-'}</code></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {wsusPolicy==='n_minus_1' && policyExcludedUpdates.length > 0 && (
        <div className="card">
          <h3>Excluded by N-1 Policy ({policyExcludedUpdates.length})</h3>
          <table className="table">
            <thead><tr><th>Title</th><th>KB</th><th>Reason</th></tr></thead>
            <tbody>{policyExcludedUpdates.map((u,i)=>(
              <tr key={`excluded-${i}`}>
                <td style={{maxWidth:520,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}} title={u.Title || ''}>{u.Title || '-'}</td>
                <td>{Array.isArray(u.KBArticleIDs) ? u.KBArticleIDs.join(',') : (u.KBArticleIDs || '-')}</td>
                <td>{u.policyReason}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
