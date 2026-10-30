import React, { useCallback, useEffect, useMemo, useState } from 'react';

export default function BackupManagerPage({ API, apiFetch, useInterval }) {
  const [hosts, setHosts] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [logs, setLogs] = useState([]);
  const [selectedConfig, setSelectedConfig] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    name: '', host_id: '', type: 'file', source: '', db_type: '', retention: 5, schedule: '',
    encryption_key: '', storage_type:'local', storage_path:'', storage_config:'', compression:6, notes:''
  });
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [testMsg, setTestMsg] = useState('');

  const fetchAll = () => {
    apiFetch(`${API}/api/hosts/`).then(r => {
      if (!r.ok) throw new Error(`hosts fetch failed: ${r.status}`);
      return r.json();
    }).then(d => setHosts(Array.isArray(d) ? d : (Array.isArray(d?.items) ? d.items : []))).catch((e) => {
      console.error('BackupManager: failed to load hosts:', e);
      setHosts([]);
    });
    apiFetch(`${API}/api/backups/configs`).then(r => r.json()).then(setConfigs).catch(() => {});
  };

  useEffect(fetchAll, []);

  const createConfig = async () => {
    setLoading(true); setMsg('');
    try {
      let parsedConfig = {};
      if (formData.storage_config) {
        try { parsedConfig = JSON.parse(formData.storage_config); }
        catch (e) { setMsg('Storage config JSON invalid'); setLoading(false); return; }
      }
      const body = {
        host_id: parseInt(formData.host_id),
        name: formData.name,
        backup_type: formData.type,
        source_path: formData.source || null,
        db_type: formData.type === 'database' ? (formData.db_type || null) : null,
        retention_count: parseInt(formData.retention),
        schedule: formData.schedule || null,
        encryption_key: formData.encryption_key || null,
        storage_type: formData.storage_type,
        storage_path: formData.storage_path || null,
        storage_config: parsedConfig,
        compression_level: parseInt(formData.compression)||6,
      };
      if (!body.source_path) delete body.source_path;
      if (!body.db_type) delete body.db_type;
      if (!body.encryption_key) delete body.encryption_key;
      if (!body.schedule) delete body.schedule;

      const r = await apiFetch(`${API}/api/backups/configs`, { method: 'POST', body: JSON.stringify(body) });
      if (r.ok) {
        setMsg('Backup job created successfully!');
        setShowModal(false);
        fetchAll();
      } else {
        const d = await r.json();
        setMsg(d.detail || 'Failed to create job');
      }
    } catch (e) {
      setMsg(e.message);
    } finally {
      setLoading(false);
    }
  };

  const testStorage = async () => {
    setTestMsg('');
    try {
      let parsedConfig = {};
      if (formData.storage_config) {
        parsedConfig = JSON.parse(formData.storage_config);
      }
      const r = await apiFetch(`${API}/api/backups/storage/test`, {
        method: 'POST',
        body: JSON.stringify({
          storage_type: formData.storage_type,
          storage_path: formData.storage_path || null,
          storage_config: parsedConfig
        })
      });
      const d = await r.json();
      setTestMsg(d.ok ? `Success: ${d.message}` : `Failed: ${d.message}`);
    } catch (e) {
      setTestMsg(`Failed: ${e.message}`);
    }
  };

  const runBackup = async (id) => {
    if(!window.confirm('Trigger backup now?')) return;
    try {
      const r = await apiFetch(`${API}/api/backups/${id}/run`, { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (r.ok) {
        if (d?.job?.id) {
          window.dispatchEvent(new CustomEvent('pm-open-ops-queue', { detail: { jobId: d.job.id } }));
          alert(`Backup queued (job: ${d.job.id}). Redirecting to Operations Queue.`);
        } else {
          alert('Backup triggered!');
        }
        viewLogs(id);
      } else {
        alert(d.detail || 'Failed');
      }
    } catch (e) { alert(e.message); }
  };

  const runRestore = async (logId) => {
    if(!selectedConfig) return;
    if(!window.confirm('Restore this backup?')) return;
    try {
      const r = await apiFetch(`${API}/api/backups/${selectedConfig}/restore`, {
        method:'POST',
        body: JSON.stringify({ backup_log_id: logId })
      });
      const d = await r.json();
      alert(d.ok ? 'Restore triggered' : (d.message || 'Restore failed'));
    } catch (e) { alert(e.message); }
  };

  const viewLogs = async (id) => {
    setSelectedConfig(id);
    const r = await apiFetch(`${API}/api/backups/${id}/logs`);
    const d = await r.json();
    setLogs(d);
  };

  // Poll logs if viewing
  useInterval(() => {
    if (selectedConfig) viewLogs(selectedConfig);
  }, selectedConfig ? 3000 : null);

  return (
    <div>
      <div className="card highlight-card">
        <h2>Backup & Disaster Recovery</h2>
        <p>Manage enterprise backups for databases, files, and full systems.</p>
      </div>

      <div className="card">
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:20}}>
          <h3>Backup Jobs</h3>
          <button className="btn btn-primary" onClick={()=>setShowModal(true)}>+ New Backup Job</button>
        </div>

        {configs.length === 0 ? <p>No backup jobs configured.</p> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Host</th><th>Type</th><th>Storage</th><th>Schedule</th><th>Retention</th><th>Last Run</th><th>Actions</th></tr></thead>
            <tbody>
              {configs.map(c => {
                const h = hosts.find(x => x.id === c.host_id);
                return (
                  <tr key={c.id}>
                    <td><strong>{c.name}</strong></td>
                    <td>{h ? h.hostname : c.host_id}</td>
                    <td><span className="badge badge-info">{c.backup_type}</span></td>
                    <td>
                      <span className="badge badge-secondary" style={{marginRight:6}}>{c.storage_type||'local'}</span>
                      <span style={{fontSize:11,color:'#6b7280'}}>{c.storage_path||'—'}</span>
                    </td>
                    <td>{c.schedule || 'Manual'}</td>
                    <td>{c.retention_count}</td>
                    <td>
                      {c.last_run_status ? <span className="badge badge-info" style={{marginRight:6}}>{c.last_run_status}</span> : null}
                      <span style={{fontSize:11,color:'#6b7280'}}>{c.last_run_at ? new Date(c.last_run_at).toLocaleString() : '—'}</span>
                    </td>
                    <td style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                      <button className="btn btn-sm btn-primary" onClick={()=>runBackup(c.id)}>Run Now</button>
                      <button className="btn btn-sm" onClick={()=>viewLogs(c.id)}>Logs</button>
                      {c.next_run_at && <span className="badge badge-light" style={{fontSize:10}}>Next {new Date(c.next_run_at).toLocaleString()}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selectedConfig && (
        <div className="card">
          <div className="card-header">
            <h3>Job History</h3>
            <button className="btn btn-sm" onClick={()=>setSelectedConfig(null)}>Close</button>
          </div>
          <table className="table">
            <thead><tr><th>Status</th><th>Started</th><th>Completed</th><th>Size</th><th>Duration</th><th>Output</th><th>Restore</th></tr></thead>
            <tbody>
              {logs.map(l => (
                <tr key={l.id}>
                  <td>
                    <span className={`badge badge-${l.status==='success'?'success':l.status==='failed'?'danger':l.status==='running'?'warning':'secondary'}`}>
                      {l.status}
                    </span>
                  </td>
                  <td>{new Date(l.started_at).toLocaleString()}</td>
                  <td>{l.completed_at ? new Date(l.completed_at).toLocaleString() : '—'}</td>
                  <td>{l.file_size_bytes ? `${l.file_size_bytes} bytes` : '—'}</td>
                  <td>{l.duration_seconds ? `${Math.round(l.duration_seconds)}s` : '—'}</td>
                  <td>
                    {l.output ? (
                      <details>
                        <summary style={{cursor:'pointer',color:'#3b82f6'}}>View Output</summary>
                        <pre style={{fontSize:11,background:'#1e293b',padding:8,borderRadius:4,marginTop:4}}>{l.output}</pre>
                      </details>
                    ) : '—'}
                  </td>
                  <td>
                    {l.status === 'success' && <button className="btn btn-sm btn-secondary" onClick={()=>runRestore(l.id)}>Restore</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="modal-overlay">
          <div className="modal-card" style={{maxWidth:600}}>
            <h3>Create Backup Job</h3>
            {msg && <div className="alert alert-danger">{msg}</div>}
            
            <div className="form-row">
              <label>Name</label>
              <input className="input" value={formData.name} onChange={e=>setFormData({...formData, name: e.target.value})} placeholder="e.g. Daily DB Backup" />
            </div>

            <div className="form-row">
              <label>Host</label>
              <select className="input" value={formData.host_id} onChange={e=>setFormData({...formData, host_id: e.target.value})}>
                <option value="">Select Host</option>
                {hosts.map(h => <option key={h.id} value={h.id}>{h.hostname} ({h.ip})</option>)}
              </select>
            </div>

            <div className="form-row">
              <label>Type</label>
              <select className="input" value={formData.type} onChange={e=>setFormData({...formData, type: e.target.value})}>
                <option value="file">File / Folder</option>
                <option value="database">Database Dump</option>
                <option value="vm">VM Snapshot (Enterprise)</option>
                <option value="live">Live Sync (Enterprise)</option>
                <option value="full_system">Full System Image (Enterprise)</option>
              </select>
            </div>

            <div className="form-row">
              <label>Source Path / Connection String</label>
              <input className="input" value={formData.source} onChange={e=>setFormData({...formData, source: e.target.value})} placeholder={formData.type==='database' ? 'postgresql://user:pass@localhost/db' : '/var/www/html'} />
            </div>

            {formData.type === 'database' && (
              <div className="form-row">
                <label>DB Type</label>
                <select className="input" value={formData.db_type} onChange={e=>setFormData({...formData, db_type: e.target.value})}>
                  <option value="">Select Type</option>
                  <option value="postgres">PostgreSQL</option>
                  <option value="mysql">MySQL / MariaDB</option>
                  <option value="mongodb">MongoDB</option>
                  <option value="redis">Redis</option>
                  <option value="sqlite">SQLite</option>
                </select>
              </div>
            )}

            <div className="form-row">
              <label>Schedule (Cron Expression)</label>
              <input className="input" value={formData.schedule} onChange={e=>setFormData({...formData, schedule: e.target.value})} placeholder="0 2 * * * (Optional)" />
              <small className="text-muted">Leave empty for manual trigger only.</small>
            </div>

            <div className="form-row" style={{display:'flex',gap:16}}>
              <div style={{flex:1}}>
                <label>Retention (Count)</label>
                <input type="number" className="input" value={formData.retention} onChange={e=>setFormData({...formData, retention: e.target.value})} />
              </div>
              <div style={{flex:2}}>
                <label>Encryption Key (Optional)</label>
                <input type="password" className="input" value={formData.encryption_key} onChange={e=>setFormData({...formData, encryption_key: e.target.value})} placeholder="AES-256 Key" />
              </div>
            </div>

            <div className="form-row" style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
              <div>
                <label>Storage Type</label>
                <select className="input" value={formData.storage_type} onChange={e=>setFormData({...formData, storage_type: e.target.value})}>
                  <option value="local">Local / Mounted</option>
                </select>
                <small className="text-muted">Backups currently support local or pre-mounted filesystem paths on the managed host.</small>
              </div>
              <div>
                <label>Storage Path</label>
                <input className="input" value={formData.storage_path} onChange={e=>setFormData({...formData, storage_path: e.target.value})} placeholder="/mnt/backup" />
              </div>
            </div>

            <div className="form-row">
              <label>Storage Config (JSON)</label>
              <textarea className="input" style={{fontFamily:'monospace',minHeight:90}} placeholder='Optional local storage metadata (currently unused)'
                value={formData.storage_config} onChange={e=>setFormData({...formData, storage_config: e.target.value})} />
              <small className="text-muted">Reserved for future storage integrations. You can leave this empty for local or mounted paths.</small>
              {testMsg && <div style={{marginTop:6,fontWeight:600,color:testMsg.startsWith('Success:')?'#16a34a':'#dc2626'}}>{testMsg}</div>}
              <button className="btn btn-sm btn-secondary" style={{marginTop:6}} onClick={testStorage}>Test Connection</button>
            </div>

            <div className="form-row" style={{display:'flex',gap:16}}>
              <div style={{flex:1}}>
                <label>Compression Level</label>
                <input type="number" className="input" value={formData.compression} onChange={e=>setFormData({...formData, compression: e.target.value})} min="0" max="9" />
              </div>
              <div style={{flex:1}}>
                <label>Notes</label>
                <input className="input" value={formData.notes||''} onChange={e=>setFormData({...formData, notes: e.target.value})} placeholder="Optional notes" />
              </div>
            </div>

            <div style={{marginTop:20, textAlign:'right'}}>
              <button className="btn" onClick={()=>setShowModal(false)} style={{marginRight:10}}>Cancel</button>
              <button className="btn btn-primary" onClick={createConfig} disabled={loading}>{loading ? 'Creating...' : 'Create Job'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Policy Manager ─── */
