import React, { useState, useEffect, useCallback } from 'react';

export function OfflinePatchPage({ hosts, allowedOS = 'all', channelTitle = 'Offline Patching and Air-Gapped Setup', API, apiFetch, useInterval }) {
  const [selectedHost, setSelectedHost] = useState('');
  const [offlinePkgs, setOfflinePkgs] = useState([]);
  const [masterPkgs, setMasterPkgs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [autoSnapshot, setAutoSnapshot] = useState(true);
  const [autoRollback, setAutoRollback] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [showPushModal, setShowPushModal] = useState(false);
  const [toast, setToast] = useState(null);
  const [availableUpdates, setAvailableUpdates] = useState([]);
  const [selectedUpdates, setSelectedUpdates] = useState([]);
  const [updatePolicy, setUpdatePolicy] = useState('latest');
  const [intakeJobId, setIntakeJobId] = useState(null);
  const [intakeJob, setIntakeJob] = useState(null);
  const [historyRows, setHistoryRows] = useState([]);

  const scopedHosts = hosts.filter((h) => {
    const raw = String(h?.os || h?.os_type || h?.platform || '').toLowerCase();
    const isWindows = raw.includes('windows');
    if (allowedOS === 'windows') return isWindows;
    if (allowedOS === 'linux') return !isWindows;
    return true;
  });

  const showToast = (text, type='info') => {
    setToast({ text, type });
    setTimeout(() => setToast(null), 3000);
  };

  const osLabelForHost = (h) => {
    const raw = (h?.os || h?.os_type || h?.platform || '').toLowerCase();
    if (raw.includes('windows')) return 'Windows';
    if (raw.includes('mac')) return 'macOS';
    if (raw.includes('ubuntu') || raw.includes('debian') || raw.includes('centos') || raw.includes('rocky') || raw.includes('rhel') || raw.includes('linux')) return 'Linux';
    return h?.os || h?.os_type || 'Unknown';
  };

  // Poll for job status
  useInterval(() => {
    if (jobId && (!jobStatus || (jobStatus.status !== 'success' && jobStatus.status !== 'failed'))) {
      apiFetch(`${API}/api/agent/${selectedHost}/job/status`)
        .then(r => r.json())
        .then(d => setJobStatus(d))
        .catch(() => {});
    }
  }, jobId ? 2000 : null);
  useInterval(() => {
    if (!intakeJobId) return;
    apiFetch(`${API}/api/jobs/${intakeJobId}`)
      .then(r => r.json())
      .then((d) => {
        setIntakeJob(d);
        const st = String(d?.status || '').toLowerCase();
        if (st === 'success' || st === 'failed' || st === 'rolled_back') {
          setTimeout(() => fetchMasterPkgs(), 1200);
          setTimeout(() => fetchHistory(), 1200);
        }
      })
      .catch(() => {});
  }, intakeJobId ? 2500 : null);

  const fetchPkgs = useCallback(async () => {
    if (!selectedHost) return;
    setLoading(true);
    try {
      const hostObj = scopedHosts.find(h => h.ip === selectedHost);
      const r = await apiFetch(`${API}/api/agent/${selectedHost}/offline/list`);
      setOfflinePkgs((await r.json()).pkgs || []);
    } catch { setOfflinePkgs([]); }
    setLoading(false);
  }, [selectedHost, scopedHosts]);
  const fetchAvailableUpdates = useCallback(async () => {
    if (!selectedHost) return;
    setLoading(true);
    try {
      const hostObj = scopedHosts.find(h => h.ip === selectedHost);
      if (!hostObj) return;
      const osName = String(hostObj.os || '').toLowerCase();
      if (osName.includes('windows')) {
        const r = await apiFetch(`${API}/api/agent/${selectedHost}/wsus/updates`);
        const d = await r.json().catch(() => ({}));
        const rows = d.updates || [];
        setAvailableUpdates(rows.map(u => ({ key: u.UpdateID, name: u.Title || u.UpdateID, raw: u })));
      } else {
        const r = await apiFetch(`${API}/api/agent/${selectedHost}/packages/upgradable`);
        const d = await r.json().catch(() => ({}));
        const rows = d.packages || [];
        setAvailableUpdates(rows.map(u => ({ key: u.name, name: `${u.name} (${u.current_version || 'unknown'} -> ${u.available_version || 'unknown'})`, raw: u })));
      }
      setSelectedUpdates([]);
    } catch {
      setAvailableUpdates([]);
    }
    setLoading(false);
  }, [selectedHost, scopedHosts]);
  const fetchHistory = useCallback(async () => {
    if (!selectedHost) { setHistoryRows([]); return; }
    const hostObj = scopedHosts.find(h => h.ip === selectedHost);
    if (!hostObj?.id) { setHistoryRows([]); return; }
    try {
      const r = await apiFetch(`${API}/api/jobs?host_id=${hostObj.id}&limit=25`);
      const d = await r.json().catch(() => []);
      setHistoryRows(Array.isArray(d) ? d : []);
    } catch {
      setHistoryRows([]);
    }
  }, [selectedHost, scopedHosts]);

  const fetchMasterPkgs = async () => {
    try {
      const r = await apiFetch(`${API}/api/packages/local/`);
      setMasterPkgs((await r.json()).packages || []);
    } catch { setMasterPkgs([]); }
  };

  useEffect(() => { fetchPkgs(); }, [fetchPkgs]);
  useEffect(() => { if (showPushModal) fetchMasterPkgs(); }, [showPushModal]);
  useEffect(() => { fetchHistory(); }, [fetchHistory]);
  useEffect(() => {
    const st = String(jobStatus?.status || '').toLowerCase();
    if (st === 'success' || st === 'failed' || st === 'rolled_back') {
      fetchHistory();
    }
  }, [jobStatus, fetchHistory]);
  useEffect(() => {
    if (selectedHost && !scopedHosts.some(h => h.ip === selectedHost)) {
      setSelectedHost('');
      setOfflinePkgs([]);
      setSelectedFiles([]);
    }
  }, [selectedHost, scopedHosts]);

  const pushFromMaster = async (filename) => {
    const hostObj = scopedHosts.find(h => h.ip === selectedHost);
    if (!hostObj) return;
    setLoading(true);
    try {
      const r = await apiFetch(`${API}/api/packages/local/push/${hostObj.id}?filename=${filename}`, { method: 'POST' });
      const payload = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast(`Pushed ${filename} to agent`,'success');
        fetchPkgs();
        setShowPushModal(false);
      } else {
        const detail = payload?.detail && typeof payload.detail === 'object' ? payload.detail : payload;
        const message = detail?.message || payload?.message || 'Push failed';
        const reason = detail?.reason || detail?.agent_response?.detail || detail?.agent_response?.raw || '';
        showToast(reason ? `${message}: ${String(reason).slice(0, 140)}` : message,'danger');
      }
    } catch(e) { showToast('Error: ' + e.message,'danger'); }
    setLoading(false);
  };

  const installOffline = async () => {
    const hostRow = scopedHosts.find(h => h.ip === selectedHost);
    if (!hostRow) return showToast('Host is outside selected channel scope','danger');
    if (!window.confirm(`Install ${selectedFiles.length || 'ALL'} package(s) on ${selectedHost}?`)) return;
    setJobId(null); setJobStatus(null); setLoading(true);
    try {
      const r = await apiFetch(`${API}/api/agent/${selectedHost}/offline/install`, {
        method: 'POST',
        body: JSON.stringify({ files: selectedFiles.length > 0 ? selectedFiles : [], auto_snapshot: autoSnapshot, auto_rollback: autoRollback })
      });
      const d = await r.json();
      if (d.status === 'started') {
        setJobId('offline_install'); // Agent only tracks one job at a time, so ID doesn't matter much for direct polling
      } else {
        showToast('Failed to start job: ' + JSON.stringify(d),'danger');
      }
      fetchPkgs();
    } catch (e) { showToast('Error: ' + e.message,'danger'); }
    setLoading(false);
  };
  const downloadUpdatesOnly = async () => {
    const hostObj = scopedHosts.find(h => h.ip === selectedHost);
    if (!hostObj) return showToast('Select valid host', 'danger');
    const osName = String(hostObj.os || '').toLowerCase();
    try {
      if (osName.includes('windows')) {
        const ids = selectedUpdates.length ? selectedUpdates : availableUpdates.map(u => u.key).filter(Boolean);
        if (!ids.length) return showToast('No updates selected', 'danger');
        const r = await apiFetch(`${API}/api/agent/${selectedHost}/wsus/download`, { method:'POST', body: JSON.stringify({ update_ids: ids }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) return showToast(d.error || 'Download failed', 'danger');
        showToast(`Download started for ${ids.length} update(s)`, 'success');
        return;
      }
      const names = selectedUpdates.length ? selectedUpdates : availableUpdates.map(u => u.key).filter(Boolean);
      const r = await apiFetch(`${API}/api/agent/${selectedHost}/patch/server-patch`, {
        method:'POST',
        body: JSON.stringify({ packages: names, download_only: true, save_to_repo: true, update_policy: updatePolicy }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return showToast(d.detail?.message || d.error || 'Intake failed', 'danger');
      setIntakeJobId(d.job_id || null);
      setIntakeJob({ status:'running', id:d.job_id });
      showToast('Download-only intake started. Packages will be stored in local repository.', 'success');
    } catch {
      showToast('Intake failed', 'danger');
    }
  };

  const clearPkgs = async () => {
    if (!window.confirm('Remove all package files?')) return;
    await apiFetch(`${API}/api/agent/${selectedHost}/cleanup`, { method: 'POST', body: JSON.stringify({package_retention_days: 0}) });
    fetchPkgs();
  };

  return (
    <div>
      {toast && (
        <div style={{
          position:'fixed', bottom:20, right:20, padding:'12px 16px', borderRadius:8,
          background: toast.type==='success' ? '#0f5132' : toast.type==='danger' ? '#842029' : '#1e293b',
          color: '#fff', boxShadow:'0 10px 20px rgba(0,0,0,0.25)', zIndex:2000
        }}>
          {toast.text}
        </div>
      )}
      <div className="card highlight-card">
        <h3>{channelTitle}</h3>
        <p>Transparent flow: mirror online repositories into local repository, then push from local repository to target servers in a controlled manner.</p>
      </div>

      <div className="card">
        <h3>Select Target Host</h3>
        <select className="input" value={selectedHost} onChange={e => {setSelectedHost(e.target.value); setJobId(null); setJobStatus(null);}}>
          <option value="">-- Select Host --</option>
          {scopedHosts.map(h => <option key={h.id} value={h.ip}>{h.hostname || h.name} ({h.ip}) - {osLabelForHost(h)}</option>)}
        </select>
        {selectedHost && (
          <p className="text-muted" style={{marginTop:6}}>
            Detected OS: <strong>{osLabelForHost(scopedHosts.find(h=>h.ip===selectedHost))}</strong>
          </p>
        )}
      </div>

      {selectedHost && (
        <>
          <div className="card">
            <div className="card-header">
              <h3>Available Updates Intake ({availableUpdates.length})</h3>
              <div className="btn-group">
                <select className="input" style={{minWidth:160}} value={updatePolicy} onChange={e=>setUpdatePolicy(e.target.value)}>
                  <option value="latest">Policy: Latest</option>
                  <option value="security">Policy: Security</option>
                </select>
                <button className="btn btn-sm btn-primary" onClick={fetchAvailableUpdates}>Check Available Updates</button>
                <button className="btn btn-sm btn-warning" onClick={downloadUpdatesOnly}>
                  {selectedUpdates.length ? `Download Selected (${selectedUpdates.length})` : `Download All (${availableUpdates.length})`}
                </button>
              </div>
            </div>
            {intakeJob && (
              <div style={{marginBottom:10}}>
            <span className="badge badge-info">Intake Job #{intakeJob.id || intakeJobId || '-'}: {intakeJob.status || 'running'}</span>
              </div>
            )}
            {availableUpdates.length === 0 ? (
              <p className="text-muted" style={{ padding: '1rem' }}>No available updates loaded yet. Click "Check Available Updates".</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th style={{width:60}}>
                      <input
                        type="checkbox"
                        checked={selectedUpdates.length > 0 && selectedUpdates.length === availableUpdates.length}
                        onChange={(e)=>setSelectedUpdates(e.target.checked ? availableUpdates.map(x=>x.key) : [])}
                      />
                    </th>
                    <th>Update / Package</th>
                  </tr>
                </thead>
                <tbody>
                  {availableUpdates.map((u, idx) => (
                    <tr key={`available-update-${idx}`}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedUpdates.includes(u.key)}
                          onChange={()=>setSelectedUpdates(prev => prev.includes(u.key) ? prev.filter(x=>x!==u.key) : [...prev, u.key])}
                        />
                      </td>
                      <td>{u.name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <div className="card-header">
              <h3>Agent Local Storage ({offlinePkgs.length})</h3>
              <div className="btn-group">
                <button className="btn btn-sm btn-primary" onClick={() => setShowPushModal(true)}>Push from Master Repo</button>
                <button className="btn btn-sm" onClick={fetchPkgs}>Refresh</button>
                <button className="btn btn-sm btn-danger" onClick={clearPkgs}>Clear All</button>
              </div>
            </div>
            {offlinePkgs.length === 0 ? (
              <p className="text-muted" style={{ padding: '1rem' }}>No packages found on agent storage. Push from Master or upload via SCP.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: '60px' }}>Select</th>
                    <th>Filename</th>
                    <th>Size</th>
                  </tr>
                </thead>
                <tbody>
                  {offlinePkgs.map((d, i) => (
                    <tr key={i} className={selectedFiles.includes(d.name) ? 'row-selected' : ''}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedFiles.includes(d.name)}
                          onChange={() => setSelectedFiles(prev => prev.includes(d.name) ? prev.filter(f => f !== d.name) : [...prev, d.name])}
                        />
                      </td>
                      <td><strong>{d.name}</strong></td>
                      <td>{d.size_mb} MB</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <h3>Installation Options</h3>
            <div className="options-grid">
              <label className="toggle-option"><input type="checkbox" checked={autoSnapshot} onChange={e => setAutoSnapshot(e.target.checked)} /> Auto-Snapshot</label>
              <label className="toggle-option"><input type="checkbox" checked={autoRollback} onChange={e => setAutoRollback(e.target.checked)} /> Auto-Rollback</label>
            </div>
            <div style={{ marginTop: 16 }}>
              <button className="btn btn-lg btn-success" onClick={installOffline} disabled={loading || offlinePkgs.length === 0 || (jobId && jobStatus?.status === 'running')}>
                {jobId && jobStatus?.status === 'running' ? 'Installing...' : `Install ${selectedFiles.length || 'All'} Package(s)`}
              </button>
            </div>
          </div>

          <div className="card">
            <h3>Patch History (Time / Date)</h3>
            {historyRows.length === 0 ? (
              <p className="text-muted">No patch jobs found yet for this host.</p>
            ) : (
              <table className="table">
                <thead><tr><th>ID</th><th>Action</th><th>Status</th><th>Started</th><th>Completed</th></tr></thead>
                <tbody>
                  {historyRows.map((h) => (
                    <tr key={`hist-${h.id}`}>
                      <td>#{h.id}</td>
                    <td>{h.action || '-'}</td>
                    <td>{h.status || '-'}</td>
                    <td>{h.started_at ? new Date(h.started_at).toLocaleString() : '-'}</td>
                    <td>{h.completed_at ? new Date(h.completed_at).toLocaleString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {jobStatus && (
        <div className={`card ${jobStatus.status==='success'?'result-success':jobStatus.status==='failed'?'result-failure':'result-running'}`} style={{background: jobStatus.status==='running'?'#fffbeb':undefined}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
            <h3>Status: {jobStatus.status.toUpperCase()}</h3>
            {jobStatus.status === 'running' && <span className="spinner"></span>}
          </div>
          {jobStatus.log && (
            <div style={{background:'#1e293b', color:'#e2e8f0', padding:12, borderRadius:6, fontFamily:'monospace', whiteSpace:'pre-wrap', maxHeight:300, overflowY:'auto'}}>
              {jobStatus.log.join('\n') || 'Processing...'}
            </div>
          )}
          {jobStatus.last_result && <details><summary>Final Result</summary><pre className="code-block">{JSON.stringify(jobStatus.last_result,null,2)}</pre></details>}
        </div>
      )}

      {showPushModal && (
        <div className="modal-overlay">
          <div className="modal-card" style={{ maxWidth: 600 }}>
            <h3>Push Package to {selectedHost}</h3>
            <p style={{ color: '#9ca3af', marginBottom: 20 }}>Select a package from the Master node's local repository to transfer to the air-gapped agent.</p>
            <div style={{ maxHeight: 300, overflowY: 'auto', marginBottom: 20 }}>
              <table className="table">
                <thead><tr><th>Package</th><th>Size</th><th>Action</th></tr></thead>
                <tbody>
                  {masterPkgs.map(p => (
                    <tr key={p.name}>
                      <td>{p.name}</td>
                      <td>{p.size_mb} MB</td>
                      <td><button className="btn btn-sm btn-primary" onClick={() => pushFromMaster(p.name)}>Push</button></td>
                    </tr>
                  ))}
                  {masterPkgs.length === 0 && <tr><td colSpan="3" style={{ textAlign: 'center', color: '#666' }}>Local repository is empty.</td></tr>}
                </tbody>
              </table>
            </div>
            <div style={{ textAlign: 'right' }}>
              <button className="btn btn-secondary" onClick={() => setShowPushModal(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
