import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, apiFetch, hasRole } from './appRuntime';

export function UnifiedPatchHistoryPage({ hosts, jobs }) {
  const presetStorageKey = 'pm_patch_history_presets_v1';
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [hostFilter, setHostFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [osFilter, setOsFilter] = useState('all');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [patchOnly, setPatchOnly] = useState(true);
  const [selectedPreset, setSelectedPreset] = useState('none');
  const [presetName, setPresetName] = useState('');
  const [customPresets, setCustomPresets] = useState([]);
  const [serverPresets, setServerPresets] = useState([]);
  const [presetScope, setPresetScope] = useState('user');
  const [presetRole, setPresetRole] = useState('operator');
  const [presetSaving, setPresetSaving] = useState(false);
  const patchActions = useMemo(() => new Set(['server_patch', 'upgrade', 'offline_install', 'windows_update', 'patch', 'wsus_download']), []);

  const hostById = useMemo(() => {
    const m = new Map();
    hosts.forEach(h => m.set(String(h.id), h));
    return m;
  }, [hosts]);

  const hostOsChannel = (host) => {
    const raw = String(host?.os || host?.os_type || host?.platform || '').toLowerCase();
    return raw.includes('windows') ? 'windows' : 'linux';
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch(`${API}/api/jobs?limit=500`);
      const d = await r.json().catch(() => []);
      setRows(Array.isArray(d) ? d : []);
    } catch {
      setRows(Array.isArray(jobs) ? jobs : []);
    }
    setLoading(false);
  }, [jobs]);

  useEffect(() => { refresh(); }, [refresh]);
  const fetchServerPresets = useCallback(async () => {
    try {
      const r = await apiFetch(`${API}/api/patch-history/presets`);
      const d = await r.json().catch(() => []);
      setServerPresets(Array.isArray(d) ? d : []);
    } catch {
      setServerPresets([]);
    }
  }, []);
  useEffect(() => { fetchServerPresets(); }, [fetchServerPresets]);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(presetStorageKey);
      const parsed = raw ? JSON.parse(raw) : [];
      setCustomPresets(Array.isArray(parsed) ? parsed : []);
    } catch {
      setCustomPresets([]);
    }
  }, []);

  const todayStr = new Date().toISOString().slice(0, 10);
  const daysAgoStr = (days) => {
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  };
  const builtInPresets = useMemo(() => ([
    { id: 'fail-24h', label: 'Last 24h failures', filters: { hostFilter: 'all', statusFilter: 'failed', osFilter: 'all', fromDate: daysAgoStr(1), toDate: todayStr, patchOnly: true } },
    { id: 'win-7d', label: 'Windows last 7 days', filters: { hostFilter: 'all', statusFilter: 'all', osFilter: 'windows', fromDate: daysAgoStr(7), toDate: todayStr, patchOnly: true } },
    { id: 'linux-7d', label: 'Linux last 7 days', filters: { hostFilter: 'all', statusFilter: 'all', osFilter: 'linux', fromDate: daysAgoStr(7), toDate: todayStr, patchOnly: true } },
  ]), [todayStr]);

  const applyPresetFilters = (filters) => {
    if (!filters) return;
    setHostFilter(filters.hostFilter || 'all');
    setStatusFilter(filters.statusFilter || 'all');
    setOsFilter(filters.osFilter || 'all');
    setFromDate(filters.fromDate || '');
    setToDate(filters.toDate || '');
    setPatchOnly(filters.patchOnly !== false);
  };
  const allPresetOptions = [
    ...builtInPresets.map(p => ({ id: `builtin:${p.id}`, label: p.label, filters: p.filters })),
    ...serverPresets.map(p => ({ id: `server:${p.id}`, label: `${p.name} [${p.scope_type}]`, filters: p.filters || {} })),
    ...customPresets.map(p => ({ id: `custom:${p.id}`, label: p.label, filters: p.filters })),
  ];
  const applySelectedPreset = () => {
    const p = allPresetOptions.find(x => x.id === selectedPreset);
    if (!p) return;
    applyPresetFilters(p.filters);
  };
  const saveCurrentPreset = async () => {
    const label = (presetName || '').trim();
    if (!label) return;
    setPresetSaving(true);
    try {
      const desiredScope = hasRole('admin') ? presetScope : 'user';
      const payload = {
        name: label,
        scope_type: desiredScope,
        role: desiredScope === 'role' ? presetRole : null,
        filters: { hostFilter, statusFilter, osFilter, fromDate, toDate, patchOnly },
      };
      const r = await apiFetch(`${API}/api/patch-history/presets`, { method:'POST', body: JSON.stringify(payload) });
      if (r.ok) {
        const created = await r.json().catch(() => null);
        await fetchServerPresets();
        setSelectedPreset(created?.id ? `server:${created.id}` : 'none');
        setPresetName('');
        setPresetSaving(false);
        return;
      }
    } catch {}
    const entry = { id: `preset-${Date.now()}`, label, filters: { hostFilter, statusFilter, osFilter, fromDate, toDate, patchOnly } };
    const next = [...customPresets, entry];
    setCustomPresets(next);
    localStorage.setItem(presetStorageKey, JSON.stringify(next));
    setPresetName('');
    setPresetSaving(false);
  };
  const deleteCurrentPreset = async () => {
    if (String(selectedPreset || '').startsWith('server:')) {
      const id = selectedPreset.split(':')[1];
      try {
        const r = await apiFetch(`${API}/api/patch-history/presets/${id}`, { method:'DELETE' });
        if (r.ok) {
          await fetchServerPresets();
          setSelectedPreset('none');
        }
      } catch {}
      return;
    }
    if (!String(selectedPreset || '').startsWith('custom:')) return;
    const id = selectedPreset.split(':')[1];
    const next = customPresets.filter(p => p.id !== id);
    setCustomPresets(next);
    localStorage.setItem(presetStorageKey, JSON.stringify(next));
    setSelectedPreset('none');
  };

  const filtered = useMemo(() => {
    const fromTs = fromDate ? Date.parse(fromDate) : null;
    const toTs = toDate ? Date.parse(`${toDate}T23:59:59`) : null;
    return (rows || []).filter((j) => {
      const action = String(j.action || '').toLowerCase();
      if (patchOnly && !patchActions.has(action)) return false;
      if (hostFilter !== 'all' && String(j.host_id || '') !== hostFilter) return false;
      if (statusFilter !== 'all' && String(j.status || '').toLowerCase() !== statusFilter) return false;
      const host = hostById.get(String(j.host_id || ''));
      const channel = hostOsChannel(host);
      if (osFilter !== 'all' && channel !== osFilter) return false;
      const ts = Date.parse(j.started_at || j.created_at || '');
      if (fromTs && Number.isFinite(ts) && ts < fromTs) return false;
      if (toTs && Number.isFinite(ts) && ts > toTs) return false;
      return true;
    }).sort((a,b) => Date.parse(b.started_at || b.created_at || 0) - Date.parse(a.started_at || a.created_at || 0));
  }, [rows, patchOnly, hostFilter, statusFilter, osFilter, fromDate, toDate, patchActions, hostById]);

  const exportCsv = () => {
    const header = ['Job ID','Host','IP','OS','Action','Status','Started At','Completed At'];
    const lines = [header.join(',')];
    filtered.forEach((j) => {
      const host = hostById.get(String(j.host_id || ''));
      const row = [
        j.id ?? '',
        (host?.hostname || host?.name || '').replace(/,/g, ' '),
        host?.ip || '',
        host?.os || '',
        j.action || '',
        j.status || '',
        j.started_at || '',
        j.completed_at || '',
      ];
      lines.push(row.map(x => `"${String(x ?? '').replace(/"/g, '""')}"`).join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `patch-history-${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <div className="card">
        <h3>Unified Patch History</h3>
        <p className="text-muted">Combined Windows and Linux patch timeline with strict filters to avoid mix-up.</p>
        <div className="form-row">
          <select className="input" value={selectedPreset} onChange={e=>setSelectedPreset(e.target.value)} style={{maxWidth:260}}>
            <option value="none">Preset: None</option>
            {allPresetOptions.map(p => <option key={`preset-opt-${p.id}`} value={p.id}>{p.label}</option>)}
          </select>
          <button className="btn btn-sm" onClick={applySelectedPreset} disabled={selectedPreset==='none'}>Apply Preset</button>
          {hasRole('admin') && (
            <>
              <select className="input" value={presetScope} onChange={e=>setPresetScope(e.target.value)} style={{maxWidth:150}}>
                <option value="user">Scope: User</option>
                <option value="role">Scope: Role</option>
                <option value="global">Scope: Global</option>
              </select>
              {presetScope === 'role' && (
                <select className="input" value={presetRole} onChange={e=>setPresetRole(e.target.value)} style={{maxWidth:140}}>
                  <option value="admin">admin</option>
                  <option value="operator">operator</option>
                  <option value="auditor">auditor</option>
                  <option value="viewer">viewer</option>
                </select>
              )}
            </>
          )}
          <input className="input" placeholder="Save current preset as..." value={presetName} onChange={e=>setPresetName(e.target.value)} style={{maxWidth:240}} />
          <button className="btn btn-sm btn-secondary" onClick={saveCurrentPreset} disabled={!presetName.trim() || presetSaving}>{presetSaving ? 'Saving...' : 'Save Preset'}</button>
          <button className="btn btn-sm btn-danger" onClick={deleteCurrentPreset} disabled={!(String(selectedPreset||'').startsWith('custom:') || String(selectedPreset||'').startsWith('server:'))}>Delete Preset</button>
          <select className="input" value={hostFilter} onChange={e=>setHostFilter(e.target.value)} style={{maxWidth:260}}>
            <option value="all">All Hosts</option>
            {hosts.map(h => <option key={`history-host-${h.id}`} value={String(h.id)}>{h.hostname || h.name} ({h.ip})</option>)}
          </select>
          <select className="input" value={osFilter} onChange={e=>setOsFilter(e.target.value)} style={{maxWidth:170}}>
            <option value="all">All OS</option>
            <option value="linux">Linux only</option>
            <option value="windows">Windows only</option>
          </select>
          <select className="input" value={statusFilter} onChange={e=>setStatusFilter(e.target.value)} style={{maxWidth:170}}>
            <option value="all">All Status</option>
            <option value="running">Running</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
            <option value="pending_approval">Pending Approval</option>
          </select>
          <input className="input" type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)} style={{maxWidth:170}} />
          <input className="input" type="date" value={toDate} onChange={e=>setToDate(e.target.value)} style={{maxWidth:170}} />
          <label className="toggle-option"><input type="checkbox" checked={patchOnly} onChange={e=>setPatchOnly(e.target.checked)} /> Patch Actions Only</label>
          <button className="btn btn-secondary" onClick={refresh} disabled={loading}>{loading ? 'Refreshing...' : 'Refresh'}</button>
          <button className="btn btn-primary" onClick={exportCsv}>Export CSV</button>
        </div>
      </div>
      <div className="card">
        <h3>History Rows ({filtered.length})</h3>
        {filtered.length === 0 ? (
          <p className="text-muted">No matching records in selected filters.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Host</th>
                <th>IP</th>
                <th>OS</th>
                <th>Action</th>
                <th>Status</th>
                <th>Started</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((j) => {
                const host = hostById.get(String(j.host_id || ''));
                return (
                  <tr key={`patch-history-row-${j.id}`}>
                    <td>#{j.id}</td>
                    <td>{host?.hostname || host?.name || 'Unknown'}</td>
                    <td>{host?.ip || '-'}</td>
                    <td>{host?.os || '-'}</td>
                    <td>{j.action || '-'}</td>
                    <td>{j.status || '-'}</td>
                    <td>{j.started_at ? new Date(j.started_at).toLocaleString() : '-'}</td>
                    <td>{j.completed_at ? new Date(j.completed_at).toLocaleString() : '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
