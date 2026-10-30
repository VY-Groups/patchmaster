import React, { useState, useEffect, useCallback } from 'react';

export function SnapshotsPage({ hosts, API, apiFetch, authHeaders }) {
  const [selectedHostId, setSelectedHostId] = useState('');
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(false);
  const [snapName, setSnapName] = useState('');
  const [snapMode, setSnapMode] = useState('packages');
  const [serviceList, setServiceList] = useState('');
  const [windowsBackupTarget, setWindowsBackupTarget] = useState('');
  const [actionResult, setActionResult] = useState(null);
  const [createState, setCreateState] = useState('idle');
  const selectedHostRow = hosts.find(h => String(h.id) === String(selectedHostId));
  const selectedHost = selectedHostRow?.ip || '';
  const selectedHostOs = (selectedHostRow?.os || '').toLowerCase();
  const isWindowsHost = selectedHostOs.includes('win');

  const fetchSnapshots = useCallback(async () => {
    if (!selectedHostId) return;
    setLoading(true);
    try { const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/list`); const d = await r.json(); setSnapshots(d.snapshots||[]); } catch { setSnapshots([]); }
    setLoading(false);
  }, [selectedHostId]);

  useEffect(() => { fetchSnapshots(); }, [fetchSnapshots]);

  const createSnap = async () => {
    setActionResult(null);
    setCreateState('running');
    try {
      const services = serviceList.split(',').map(s=>s.trim()).filter(Boolean);
      const payload = {
        name:snapName||undefined,
        mode:snapMode,
        services,
        backup_target: windowsBackupTarget.trim() || undefined,
      };
      const pre = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/precheck`, {
        method:'POST',
        body: JSON.stringify(payload),
      });
      const preData = await pre.json().catch(()=>({ ok: false, error: `Precheck failed (${pre.status})` }));
      if (!pre.ok || preData.ok === false) {
        setCreateState('failed');
        setActionResult({ success:false, status:'failed', error: preData.error || 'Precheck failed', error_code: preData.error_code || 'precheck_failed', precheck: preData });
        return;
      }
      const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/create`, {
        method:'POST',
        body: JSON.stringify(payload)
      });
      const d = await r.json();
      setActionResult(d);
      setCreateState(d.success ? 'success' : 'failed');
      if (d.success) {
        setSnapName('');
        fetchSnapshots();
      }
    } catch (e) {
      setCreateState('failed');
      setActionResult({success:false,error:e.message,status:'failed'});
    }
  };
  const rollbackSnap = async (name) => {
    if (!window.confirm(`ROLLBACK to snapshot "${name}"?`)) return;
    try { const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/rollback`, { method:'POST', body:JSON.stringify({name}) }); setActionResult(await r.json()); } catch(e) { setActionResult({error:e.message}); }
  };
  const deleteSnap = async (name) => {
    if (!window.confirm(`Delete snapshot "${name}"?`)) return;
    try { await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/delete`, { method:'POST', body:JSON.stringify({name}) }); fetchSnapshots(); } catch {}
  };

  const archiveSnap = async (name) => {
    try {
      const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/archive/${name}`);
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setActionResult(d && Object.keys(d).length ? d : { success: false, error: `Export failed (${r.status})` });
        return;
      }
      const blob = await r.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const fallback = `${name}.tar.gz`;
      const cd = r.headers.get('content-disposition') || '';
      const match = cd.match(/filename="?([^"]+)"?/i);
      a.href = href;
      a.download = (match && match[1]) ? match[1] : fallback;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (e) {
      setActionResult({ success: false, error: e.message });
    }
  };

  const restoreSnap = async (name) => {
    if (!window.confirm(`Restore snapshot "${name}" on ${selectedHost || 'selected host'}? This overwrites the system (Linux).`)) return;
    try {
      const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/rollback`, { method:'POST', body: JSON.stringify({name}) });
      const d = await r.json();
      setActionResult(d);
      if (!d.success) alert(d.error || 'Restore failed');
    } catch (e) { alert(e.message); }
  };

  const restoreFromUrl = async () => {
    const url = window.prompt('Enter snapshot archive URL');
    if (!url) return;
    try {
      const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/restore-url`, { method:'POST', body: JSON.stringify({url}) });
      const d = await r.json();
      setActionResult(d);
    } catch (e) { alert(e.message); }
  };

  const restoreFromFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`${API}/api/agent/by-host/${selectedHostId}/snapshot/restore-upload`, { method:'POST', body: fd, headers: authHeaders() });
      const d = await r.json();
      setActionResult(d);
    } catch (err) { alert(err.message); }
    e.target.value = '';
  };

  const cloneSnap = async (name) => {
    const targetIp = window.prompt('Clone to target host IP:');
    if (!targetIp) return;
    try {
      const r = await apiFetch(`${API}/api/agent/clone-snapshot`, { method:'POST', body: JSON.stringify({source_ip:selectedHost, target_ip:targetIp, name}) });
      const d = await r.json();
      setActionResult(d);
      if (!d.success && d.error) alert(d.error);
    } catch (e) { alert(e.message); }
  };

  const cleanup = async () => {
    if(!window.confirm('Delete snapshots older than 30 days?')) return;
    try {
      const r = await apiFetch(`${API}/api/agent/by-host/${selectedHostId}/cleanup`, { method:'POST', body: JSON.stringify({snapshot_retention_days: 30}) });
      const d = await r.json();
      alert(`Deleted ${d.deleted_snapshots.length} snapshots and ${d.deleted_packages.length} packages.`);
      fetchSnapshots();
    } catch(e) { alert(e.message); }
  };

  return (
    <div>
      <div className="card highlight-card"><h3>Image & Snapshot Center</h3><p>Create package or full-system images, export them, restore them, or clone them to another host as part of recovery and image-based provisioning workflows.</p></div>
      <div className="card"><h3>Select Host</h3><select className="input" value={selectedHostId} onChange={e=>setSelectedHostId(e.target.value)}><option value="">-- Select Host --</option>{hosts.map(h=><option key={h.id} value={String(h.id)}>{h.hostname||h.name} ({h.ip})</option>)}</select></div>
      {selectedHostId && <>
        <div className="card">
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10}}>
            <h3>Create Snapshot</h3>
            <div className="btn-group">
              <button className="btn btn-sm btn-secondary" onClick={restoreFromUrl}>Restore from URL</button>
              <label className="btn btn-sm btn-secondary" style={{cursor:'pointer'}}>
                Restore from file
                <input type="file" style={{display:'none'}} onChange={restoreFromFile} />
              </label>
              <button className="btn btn-sm btn-danger" onClick={cleanup}>Cleanup Old</button>
            </div>
          </div>
          <div className="card" style={{marginBottom:10, background:'#fff8e6', border:'1px solid #f59e0b'}}>
            <strong>Important:</strong> Windows full-system restore uses wbadmin and requires Admin; may prompt OS dialogs. Linux full-system restore overwrites the filesystem. Ensure backups, free disk space, and planned downtime.
          </div>
          <div className="form-row">
            <input className="input" placeholder="Snapshot name (optional)" value={snapName} onChange={e=>setSnapName(e.target.value)} style={{flex:1}} />
            <select className="input" value={snapMode} onChange={e=>setSnapMode(e.target.value)} style={{width:200}}>
              <option value="packages">Services + Packages</option>
              <option value="services">Services only</option>
              <option value="selected_services">Selected services</option>
              <option value="full_system">Full system image</option>
            </select>
            <button className="btn btn-success" onClick={createSnap} disabled={createState==='running'}>{createState==='running'?'Creating...':'Create'}</button>
          </div>
          {snapMode==='selected_services' && (
            <div className="form-row" style={{marginTop:8}}>
              <input className="input" placeholder="service1,service2" value={serviceList} onChange={e=>setServiceList(e.target.value)} />
            </div>
          )}
          {snapMode==='full_system' && (
            <p className="text-muted" style={{marginTop:8}}>Full system image may take time and disk space. Ensure the agent runs as Admin/root and has free space.</p>
          )}
          {isWindowsHost && snapMode==='full_system' && (
            <div className="form-row" style={{marginTop:8}}>
              <input
                className="input"
                placeholder="Optional wbadmin target, e.g. \\\\server\\patchmaster-wbadmin or E:"
                value={windowsBackupTarget}
                onChange={e=>setWindowsBackupTarget(e.target.value)}
              />
            </div>
          )}
        </div>
        <div className="card"><div className="card-header"><h3>Snapshots ({snapshots.length})</h3><button className="btn btn-sm" onClick={fetchSnapshots}>{loading?'Loading...':'Refresh'}</button></div>
          {snapshots.length===0?<p className="text-muted">No snapshots found.</p>:(
            <table className="table"><thead><tr><th>Name</th><th>Mode</th><th>Created</th><th>Packages</th><th>Image Size</th><th>Actions</th></tr></thead>
            <tbody>{snapshots.map((s,i)=><tr key={i}><td><strong>{s.name}</strong></td><td>{s.mode||'packages'}</td><td>{s.created||'-'}</td><td>{s.packages_count||'-'}</td><td>{s.image_size_bytes?`${(s.image_size_bytes/1024/1024).toFixed(1)} MB`:'-'}</td><td style={{display:'flex',gap:6,flexWrap:'wrap'}}>
              <button className="btn btn-sm btn-info" onClick={()=>archiveSnap(s.name)}>Export</button>
              <button className="btn btn-sm btn-warning" onClick={()=>rollbackSnap(s.name)}>Rollback</button>
              <button className="btn btn-sm btn-secondary" onClick={()=>restoreSnap(s.name)}>Restore</button>
              <button className="btn btn-sm btn-primary" onClick={()=>cloneSnap(s.name)}>Clone</button>
              <button className="btn btn-sm btn-danger" onClick={()=>deleteSnap(s.name)}>Delete</button>
            </td></tr>)}</tbody></table>
          )}
        </div>
      </>}
      {(createState==='running' || actionResult) && (
        <div className={`card ${createState==='running' || actionResult?.success ? 'result-success' : 'result-failure'}`}>
          <h3>{createState==='running' ? 'Running' : (actionResult?.success ? 'Success' : 'Failed')}</h3>
          {createState==='running' && <p className="text-muted">Snapshot request is in progress. Full-system image can take several minutes.</p>}
          {actionResult?.status && <p><strong>Status:</strong> {String(actionResult.status).toUpperCase()}</p>}
          {actionResult?.error && <p><strong>Error:</strong> {actionResult.error}</p>}
          {actionResult?.error_code && <p><strong>Error code:</strong> {actionResult.error_code}</p>}
          {actionResult?.precheck?.checks?.length > 0 && (
            <div style={{marginTop:8}}>
              <strong>Capacity checks</strong>
              <pre className="code-block">{JSON.stringify(actionResult.precheck.checks, null, 2)}</pre>
            </div>
          )}
          <details><summary>Details</summary><pre className="code-block">{JSON.stringify(actionResult,null,2)}</pre></details>
        </div>
      )}
    </div>
  );
}
