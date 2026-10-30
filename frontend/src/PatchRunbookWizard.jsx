import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, apiFetch, getToken } from './appRuntime';

export function PatchRunbookWizard({ hosts }) {
  const storageKey = 'pm_patch_runbook_profiles_v1';
  const [channel, setChannel] = useState('linux');
  const [repos, setRepos] = useState([]);
  const [repoId, setRepoId] = useState('');
  const [packages, setPackages] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [selectedHostIds, setSelectedHostIds] = useState([]);
  const [ringSize, setRingSize] = useState(2);
  const [snapshotMode, setSnapshotMode] = useState('packages');
  const [rollbackOnFailure, setRollbackOnFailure] = useState(true);
  const [requireApproval, setRequireApproval] = useState(false);
  const [approvedBy, setApprovedBy] = useState('');
  const [maintenanceStart, setMaintenanceStart] = useState('00:00');
  const [maintenanceEnd, setMaintenanceEnd] = useState('23:59');
  const [autoIntake, setAutoIntake] = useState(true);
  const [autoSelectPackages, setAutoSelectPackages] = useState(true);
  const [maxPackageCount, setMaxPackageCount] = useState(25);
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState('template-dev');
  const [profileName, setProfileName] = useState('');
  const [serverProfiles, setServerProfiles] = useState([]);
  const [selectedServerProfileId, setSelectedServerProfileId] = useState('');
  const [scheduleName, setScheduleName] = useState('Nightly Run');
  const [scheduleCron, setScheduleCron] = useState('0 2 * * *');
  const [serverSchedules, setServerSchedules] = useState([]);
  const [serverRuns, setServerRuns] = useState([]);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([
    { key: 'approval', label: 'Approval and maintenance window', status: 'pending', detail: '' },
    { key: 'mirror', label: 'Mirror sync', status: 'pending', detail: '' },
    { key: 'local_repo', label: 'Local repo validation', status: 'pending', detail: '' },
    { key: 'precheck', label: 'Prechecks', status: 'pending', detail: '' },
    { key: 'snapshot', label: 'Snapshots', status: 'pending', detail: '' },
    { key: 'rollout', label: 'Staged rollout', status: 'pending', detail: '' },
    { key: 'postcheck', label: 'Post-check and rollback policy', status: 'pending', detail: '' },
  ]);
  const [runbookLog, setRunbookLog] = useState([]);

  const scopedHosts = hosts.filter((h) => {
    const os = String(h?.os || '').toLowerCase();
    const groups = Array.isArray(h?.groups) ? h.groups.map(g => String(g || '').toLowerCase()) : [];
    const isWindows = os.includes('windows') || groups.includes('windows');
    return channel === 'windows' ? isWindows : !isWindows;
  });

  const setStep = (key, status, detail = '') => {
    setSteps(prev => prev.map(s => s.key === key ? { ...s, status, detail } : s));
  };
  const addLog = (line) => setRunbookLog(prev => [`${new Date().toLocaleTimeString()} ${line}`, ...prev].slice(0, 300));
  const defaultTemplates = useMemo(() => ([
    { id: 'template-dev', name: 'Dev Template', channel: 'linux', ringSize: 10, snapshotMode: 'packages', rollbackOnFailure: true, requireApproval: false, maintenanceStart: '00:00', maintenanceEnd: '23:59', autoIntake: true, autoSelectPackages: true, maxPackageCount: 25 },
    { id: 'template-test', name: 'Test Template', channel: 'linux', ringSize: 5, snapshotMode: 'packages', rollbackOnFailure: true, requireApproval: true, maintenanceStart: '20:00', maintenanceEnd: '23:30', autoIntake: true, autoSelectPackages: true, maxPackageCount: 20 },
    { id: 'template-prod', name: 'Prod Template', channel: 'linux', ringSize: 2, snapshotMode: 'full_system', rollbackOnFailure: true, requireApproval: true, maintenanceStart: '22:00', maintenanceEnd: '02:00', autoIntake: true, autoSelectPackages: true, maxPackageCount: 15 },
  ]), []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      const saved = raw ? JSON.parse(raw) : [];
      if (Array.isArray(saved) && saved.length) {
        setProfiles([...defaultTemplates, ...saved]);
      } else {
        setProfiles(defaultTemplates);
      }
    } catch {
      setProfiles(defaultTemplates);
    }
  }, [defaultTemplates]);

  useEffect(() => {
    const p = profiles.find(x => x.id === selectedProfile);
    if (!p) return;
    setChannel(p.channel || 'linux');
    setRingSize(Math.max(parseInt(p.ringSize || 2), 1));
    setSnapshotMode(p.snapshotMode || 'packages');
    setRollbackOnFailure(p.rollbackOnFailure !== false);
    setRequireApproval(!!p.requireApproval);
    setMaintenanceStart(p.maintenanceStart || '00:00');
    setMaintenanceEnd(p.maintenanceEnd || '23:59');
    setAutoIntake(p.autoIntake !== false);
    setAutoSelectPackages(p.autoSelectPackages !== false);
    setMaxPackageCount(Math.max(parseInt(p.maxPackageCount || 25), 1));
  }, [selectedProfile, profiles]);

  const buildProfilePayload = () => ({
    name: profileName || `Runbook ${new Date().toLocaleDateString()}`,
    channel,
    require_approval: requireApproval,
    approval_role: 'operator',
    config: {
      host_ids: selectedHostIds.map(x => parseInt(x)),
      files: selectedFiles,
      ring_size: ringSize,
      snapshot_mode: snapshotMode,
      rollback_on_failure: rollbackOnFailure,
      maintenance_start: maintenanceStart,
      maintenance_end: maintenanceEnd,
      auto_intake: autoIntake,
      auto_select_packages: autoSelectPackages,
      max_package_count: maxPackageCount,
      approved_by: approvedBy,
      repo_ids: repoId ? [parseInt(repoId)] : [],
    },
    is_active: true,
  });

  const fetchServerRunbookData = useCallback(async () => {
    try {
      const [pr, sr, xr] = await Promise.all([
        apiFetch(`${API}/api/runbook/profiles`),
        apiFetch(`${API}/api/runbook/schedules`),
        apiFetch(`${API}/api/runbook/executions?limit=50`),
      ]);
      setServerProfiles(await pr.json().catch(() => []));
      setServerSchedules(await sr.json().catch(() => []));
      setServerRuns(await xr.json().catch(() => []));
    } catch {}
  }, []);

  useEffect(() => { fetchServerRunbookData(); }, [fetchServerRunbookData]);

  const saveCurrentProfile = async () => {
    const name = (profileName || '').trim();
    if (!name) return alert('Enter profile name');
    try {
      const r = await apiFetch(`${API}/api/runbook/profiles`, { method:'POST', body: JSON.stringify({ ...buildProfilePayload(), name }) });
      if (r.ok) {
        const p = await r.json();
        setSelectedServerProfileId(String(p.id));
        setProfileName('');
        fetchServerRunbookData();
      } else {
        const d = await r.json().catch(() => ({}));
        alert(d.detail || 'Failed to save profile on server');
      }
    } catch {}
    const id = `custom-${Date.now()}`;
    const entry = {
      id,
      name,
      channel,
      ringSize,
      snapshotMode,
      rollbackOnFailure,
      requireApproval,
      maintenanceStart,
      maintenanceEnd,
      autoIntake,
      autoSelectPackages,
      maxPackageCount,
    };
    const custom = [...profiles.filter(p => !String(p.id).startsWith('template-')).filter(p => p.id !== id), entry];
    localStorage.setItem(storageKey, JSON.stringify(custom));
    setProfiles([...defaultTemplates, ...custom]);
    setSelectedProfile(id);
  };

  useEffect(() => {
    if (!selectedServerProfileId) return;
    const p = serverProfiles.find(x => String(x.id) === String(selectedServerProfileId));
    if (!p) return;
    const cfg = p.config || {};
    setChannel(p.channel || 'linux');
    setRequireApproval(!!p.require_approval);
    setRingSize(Math.max(parseInt(cfg.ring_size || 2), 1));
    setSnapshotMode(cfg.snapshot_mode || 'packages');
    setRollbackOnFailure(cfg.rollback_on_failure !== false);
    setMaintenanceStart(cfg.maintenance_start || '00:00');
    setMaintenanceEnd(cfg.maintenance_end || '23:59');
    setAutoIntake(cfg.auto_intake !== false);
    setAutoSelectPackages(cfg.auto_select_packages !== false);
    setMaxPackageCount(Math.max(parseInt(cfg.max_package_count || 25), 1));
    setApprovedBy(cfg.approved_by || '');
    setSelectedHostIds((cfg.host_ids || []).map(x => String(x)));
    setSelectedFiles(cfg.files || []);
    const rid = Array.isArray(cfg.repo_ids) && cfg.repo_ids.length ? cfg.repo_ids[0] : '';
    setRepoId(rid ? String(rid) : '');
  }, [selectedServerProfileId, serverProfiles]);

  const createRunbookSchedule = async () => {
    if (!selectedServerProfileId) return alert('Select server profile');
    const r = await apiFetch(`${API}/api/runbook/schedules`, {
      method:'POST',
      body: JSON.stringify({
        profile_id: parseInt(selectedServerProfileId),
        name: scheduleName || 'Scheduled Run',
        cron_expression: scheduleCron || '0 2 * * *',
        timezone: 'UTC',
        is_active: true,
      }),
    });
    if (r.ok) {
      fetchServerRunbookData();
    } else {
      const d = await r.json().catch(() => ({}));
      alert(d.detail || 'Failed to create schedule');
    }
  };

  const approveSchedule = async (id) => {
    const r = await apiFetch(`${API}/api/runbook/schedules/${id}/approve`, { method:'POST' });
    if (r.ok) fetchServerRunbookData();
  };

  const executeServerProfile = async () => {
    const id = selectedServerProfileId || (serverProfiles[0] ? String(serverProfiles[0].id) : '');
    if (!id) return alert('Save or select a server profile first');
    const r = await apiFetch(`${API}/api/runbook/execute/${id}`, { method:'POST' });
    if (r.ok) {
      setTimeout(fetchServerRunbookData, 1200);
    } else {
      const d = await r.json().catch(() => ({}));
      alert(d.detail || 'Failed to queue runbook execution');
    }
  };

  const downloadRunAudit = async (runId, kind) => {
    const t = getToken();
    const resp = await fetch(`${API}/api/runbook/executions/${runId}/audit.${kind}`, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const a = document.createElement('a');
    const u = URL.createObjectURL(blob);
    const cd = resp.headers.get('content-disposition') || '';
    const filename = cd.includes('filename=') ? cd.split('filename=')[1].replace(/"/g, '').trim() : `runbook-${runId}.${kind}`;
    a.href = u; a.download = filename; a.click(); URL.revokeObjectURL(u);
  };

  const loadRepos = useCallback(async () => {
    try {
      const r = await apiFetch(`${API}/api/mirror/repos`);
      const d = await r.json().catch(() => []);
      const list = Array.isArray(d) ? d : (d.items || []);
      setRepos(list);
      if (!repoId && list.length) {
        const pick = list.find(x => String(x.os_family || '').toLowerCase() === channel) || list[0];
        if (pick?.id) setRepoId(String(pick.id));
      }
    } catch { setRepos([]); }
  }, [repoId, channel]);

  const loadLocalPackages = useCallback(async () => {
    try {
      const r = await apiFetch(`${API}/api/packages/local/`);
      const d = await r.json().catch(() => ({}));
      const list = d.packages || [];
      setPackages(list);
      if (!selectedFiles.length) setSelectedFiles(list.slice(0, 5).map(p => p.name));
    } catch { setPackages([]); }
  }, [selectedFiles.length]);

  useEffect(() => { loadRepos(); loadLocalPackages(); }, [loadRepos, loadLocalPackages]);
  useEffect(() => {
    setSelectedHostIds(prev => prev.filter(id => scopedHosts.some(h => String(h.id) === String(id))));
  }, [channel, hosts]);

  const waitForHostJob = async (hostIp, timeoutSeconds = 600) => {
    const start = Date.now();
    while ((Date.now() - start) / 1000 < timeoutSeconds) {
      const r = await apiFetch(`${API}/api/agent/${hostIp}/job/status`);
      const d = await r.json().catch(() => ({}));
      const st = String(d?.status || '').toLowerCase();
      if (st === 'success' || st === 'failed') return d;
      await new Promise(res => setTimeout(res, 3000));
    }
    return { status: 'failed', error: 'Timeout waiting for host job completion' };
  };

  const executeRunbook = async () => {
    if (!selectedHostIds.length) return alert('Select at least one host');
    setRunning(true);
    setRunbookLog([]);
    setSteps(prev => prev.map(s => ({ ...s, status: 'pending', detail: '' })));
    const selectedHosts = scopedHosts.filter(h => selectedHostIds.includes(String(h.id)));
    const snapshotByHost = {};
    let currentStep = 'approval';
    try {
      setStep('approval', 'running', 'Validating approvals and maintenance window');
      addLog('Step 0 approval and maintenance checks');
      if (requireApproval && !String(approvedBy || '').trim()) {
        throw new Error('Approval is required. Please provide approver identity.');
      }
      const now = new Date();
      const [sh, sm] = String(maintenanceStart || '00:00').split(':').map(x => parseInt(x || '0'));
      const [eh, em] = String(maintenanceEnd || '23:59').split(':').map(x => parseInt(x || '0'));
      const startM = (sh * 60) + sm;
      const endM = (eh * 60) + em;
      const nowM = (now.getHours() * 60) + now.getMinutes();
      const inWindow = startM <= endM ? (nowM >= startM && nowM <= endM) : (nowM >= startM || nowM <= endM);
      if (!inWindow) {
        throw new Error(`Current time is outside maintenance window (${maintenanceStart} - ${maintenanceEnd})`);
      }
      setStep('approval', 'success', requireApproval ? `Approved by ${approvedBy}` : 'Approval not required');

      currentStep = 'mirror';
      setStep('mirror', 'running', 'Synchronizing selected mirror repository');
      addLog('Step 1 mirror sync started');
      if (autoIntake) {
        const inScopeRepos = repos.filter(r => String(r.os_family || '').toLowerCase() === channel && r.enabled !== false);
        for (const repo of inScopeRepos) {
          const rr = await apiFetch(`${API}/api/mirror/repos/${repo.id}/sync?wait=true`, { method: 'POST' });
          if (!rr.ok) {
            const rd = await rr.json().catch(() => ({}));
            throw new Error(rd?.detail || rd?.message || `Mirror sync failed for ${repo.name}`);
          }
        }
      } else if (repoId) {
        const rr = await apiFetch(`${API}/api/mirror/repos/${repoId}/sync?wait=true`, { method: 'POST' });
        if (!rr.ok) {
          const rd = await rr.json().catch(() => ({}));
          throw new Error(rd?.detail || rd?.message || 'Mirror sync failed');
        }
      }
      setStep('mirror', 'success', 'Mirror synchronization completed');

      currentStep = 'local_repo';
      setStep('local_repo', 'running', 'Validating package existence in local repository');
      addLog('Step 2 local repo validation');
      const rp = await apiFetch(`${API}/api/packages/local/`);
      const rpd = await rp.json().catch(() => ({}));
      const availablePkgs = rpd?.packages || [];
      if (autoSelectPackages) {
        const picked = availablePkgs.slice(0, Math.max(1, maxPackageCount)).map(x => x.name);
        setSelectedFiles(picked);
      }
      const filesForRun = autoSelectPackages ? availablePkgs.slice(0, Math.max(1, maxPackageCount)).map(x => x.name) : selectedFiles;
      if (!filesForRun.length) throw new Error('No package selected or available in local repository');
      const names = new Set(availablePkgs.map(x => x.name));
      const missing = filesForRun.filter(f => !names.has(f));
      if (missing.length) throw new Error(`Local repository missing packages: ${missing.join(', ')}`);
      setStep('local_repo', 'success', `Validated ${filesForRun.length} package(s)`);

      currentStep = 'precheck';
      setStep('precheck', 'running', 'Running snapshot prechecks on selected hosts');
      addLog('Step 3 host prechecks');
      for (const host of selectedHosts) {
        const pre = await apiFetch(`${API}/api/agent/by-host/${host.id}/snapshot/precheck`, { method: 'POST', body: JSON.stringify({ mode: snapshotMode }) });
        const pd = await pre.json().catch(() => ({}));
        if (!pre.ok || pd?.ok === false) throw new Error(`Precheck failed on ${host.hostname || host.ip}: ${pd?.error || pre.status}`);
      }
      setStep('precheck', 'success', `Prechecks passed on ${selectedHosts.length} host(s)`);

      currentStep = 'snapshot';
      setStep('snapshot', 'running', 'Creating snapshots before rollout');
      addLog('Step 4 creating snapshots');
      for (const host of selectedHosts) {
        const snapName = `runbook-${channel}-${Date.now()}-${host.id}`;
        const sr = await apiFetch(`${API}/api/agent/by-host/${host.id}/snapshot/create`, { method: 'POST', body: JSON.stringify({ name: snapName, mode: snapshotMode }) });
        const sd = await sr.json().catch(() => ({}));
        if (!sr.ok || sd?.success === false) throw new Error(`Snapshot failed on ${host.hostname || host.ip}: ${sd?.error || sr.status}`);
        snapshotByHost[String(host.id)] = snapName;
      }
      setStep('snapshot', 'success', 'Snapshots created successfully');

      currentStep = 'rollout';
      setStep('rollout', 'running', `Staged rollout in rings of ${ringSize}`);
      addLog('Step 5 staged patch rollout started');
      const failedHosts = [];
      for (let i = 0; i < selectedHosts.length; i += Math.max(1, ringSize)) {
        const ring = selectedHosts.slice(i, i + Math.max(1, ringSize));
        addLog(`Running ring ${Math.floor(i / Math.max(1, ringSize)) + 1} with ${ring.length} host(s)`);
        for (const host of ring) {
          const inst = await apiFetch(`${API}/api/agent/${host.ip}/offline/install`, {
            method: 'POST',
            body: JSON.stringify({ files: filesForRun, auto_snapshot: false, auto_rollback: false })
          });
          const id = await inst.json().catch(() => ({}));
          if (!inst.ok || id?.status !== 'started') {
            failedHosts.push({ host, reason: 'start_failed' });
            continue;
          }
          const status = await waitForHostJob(host.ip, 900);
          if (String(status?.status || '').toLowerCase() !== 'success') {
            failedHosts.push({ host, reason: status?.error || 'install_failed' });
          }
        }
        if (failedHosts.length) break;
      }
      if (failedHosts.length) {
        setStep('rollout', 'failed', `Failures on ${failedHosts.map(f => f.host.hostname || f.host.ip).join(', ')}`);
        if (rollbackOnFailure) {
          addLog('Rollback policy active, attempting rollbacks on failed hosts');
          for (const f of failedHosts) {
            const snapName = snapshotByHost[String(f.host.id)];
            if (!snapName) continue;
            await apiFetch(`${API}/api/agent/by-host/${f.host.id}/snapshot/rollback`, { method: 'POST', body: JSON.stringify({ name: snapName }) });
          }
          setStep('postcheck', 'success', 'Rollback policy executed for failed hosts');
        } else {
          setStep('postcheck', 'failed', 'Rollout failed and rollback policy disabled');
        }
        throw new Error('Rollout encountered failures');
      }
      setStep('rollout', 'success', 'All rings completed successfully');

      currentStep = 'postcheck';
      setStep('postcheck', 'running', 'Collecting post-check health state');
      addLog('Step 6 post-check started');
      for (const host of selectedHosts) {
        const jr = await apiFetch(`${API}/api/agent/${host.ip}/job/status`);
        const jd = await jr.json().catch(() => ({}));
        if (String(jd?.status || '').toLowerCase() === 'failed') throw new Error(`Post-check failed on ${host.hostname || host.ip}`);
      }
      setStep('postcheck', 'success', 'Post-check completed with rollback policy intact');
      addLog('Runbook completed successfully');
    } catch (e) {
      addLog(`Runbook stopped: ${e.message}`);
      if (currentStep) setStep(currentStep, 'failed', e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <div className="card highlight-card">
        <h3>Patch Runbook Wizard</h3>
        <p>Executes end-to-end: mirror sync, local repo validation, prechecks, snapshots, staged rollout, and post-check rollback policy.</p>
      </div>
      <div className="card">
        <h3>Runbook Profiles</h3>
        <div className="form-row" style={{marginBottom:10}}>
          <select className="input" value={selectedProfile} onChange={e=>setSelectedProfile(e.target.value)} style={{maxWidth:260}}>
            {profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className="input" value={selectedServerProfileId} onChange={e=>setSelectedServerProfileId(e.target.value)} style={{maxWidth:280}}>
            <option value="">Server Profile (optional)</option>
            {serverProfiles.map(p => <option key={`srv-prof-${p.id}`} value={p.id}>{p.name} [{p.channel}]</option>)}
          </select>
          <input className="input" placeholder="Save current as profile" value={profileName} onChange={e=>setProfileName(e.target.value)} style={{maxWidth:260}} />
          <button className="btn btn-secondary" onClick={saveCurrentProfile}>Save Profile</button>
          <button className="btn btn-primary" onClick={executeServerProfile}>Run Server Profile</button>
          <button className="btn btn-sm" onClick={fetchServerRunbookData}>Refresh</button>
        </div>
      </div>
      <div className="card">
        <h3>Scheduled Profile Execution</h3>
        <div className="form-row">
          <input className="input" value={scheduleName} onChange={e=>setScheduleName(e.target.value)} style={{maxWidth:260}} placeholder="Schedule name" />
          <input className="input" value={scheduleCron} onChange={e=>setScheduleCron(e.target.value)} style={{maxWidth:220}} placeholder="Cron (UTC)" />
          <button className="btn btn-secondary" onClick={createRunbookSchedule}>Create Schedule</button>
        </div>
        {serverSchedules.length === 0 ? <p className="text-muted">No schedules created.</p> : (
          <table className="table" style={{marginTop:10}}>
            <thead><tr><th>Name</th><th>Profile</th><th>Cron</th><th>Approved</th><th>Next Run</th><th>Actions</th></tr></thead>
            <tbody>
              {serverSchedules.slice(0, 20).map(s => (
                <tr key={`runbook-schedule-${s.id}`}>
                  <td>{s.name}</td>
                  <td>{serverProfiles.find(p => p.id === s.profile_id)?.name || s.profile_id}</td>
                  <td><code>{s.cron_expression}</code></td>
                  <td>{s.approved_by || '-'}</td>
                  <td>{s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '-'}</td>
                  <td><button className="btn btn-sm btn-success" onClick={()=>approveSchedule(s.id)}>Approve</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <div className="form-row">
          <select className="input" value={channel} onChange={e => setChannel(e.target.value)} style={{maxWidth:180}}>
            <option value="linux">Linux Channel</option>
            <option value="windows">Windows Channel</option>
          </select>
          <select className="input" value={repoId} onChange={e => setRepoId(e.target.value)} style={{maxWidth:260}}>
            <option value="">Select Mirror Repository</option>
            {repos.filter(r => String(r.os_family || '').toLowerCase() === channel).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
          <input className="input" type="number" min="1" value={ringSize} onChange={e=>setRingSize(parseInt(e.target.value || 1))} style={{maxWidth:130}} placeholder="Ring size" />
          <select className="input" value={snapshotMode} onChange={e=>setSnapshotMode(e.target.value)} style={{maxWidth:190}}>
            <option value="packages">Snapshot: packages</option>
            <option value="full_system">Snapshot: full system</option>
          </select>
          <label className="toggle-option"><input type="checkbox" checked={autoIntake} onChange={e=>setAutoIntake(e.target.checked)} /> Auto intake updates</label>
          <label className="toggle-option"><input type="checkbox" checked={autoSelectPackages} onChange={e=>setAutoSelectPackages(e.target.checked)} /> Auto select packages</label>
          <input className="input" type="number" min="1" value={maxPackageCount} onChange={e=>setMaxPackageCount(parseInt(e.target.value || 1))} style={{maxWidth:160}} placeholder="Max packages" />
        </div>
        <div className="form-row" style={{marginTop:8}}>
          <label className="toggle-option"><input type="checkbox" checked={requireApproval} onChange={e=>setRequireApproval(e.target.checked)} /> Require approval</label>
          <input className="input" placeholder="Approved by" value={approvedBy} onChange={e=>setApprovedBy(e.target.value)} style={{maxWidth:220}} />
          <input className="input" type="time" value={maintenanceStart} onChange={e=>setMaintenanceStart(e.target.value)} style={{maxWidth:160}} />
          <input className="input" type="time" value={maintenanceEnd} onChange={e=>setMaintenanceEnd(e.target.value)} style={{maxWidth:160}} />
          <label className="toggle-option"><input type="checkbox" checked={rollbackOnFailure} onChange={e=>setRollbackOnFailure(e.target.checked)} /> Rollback on failure</label>
          <button className="btn btn-primary" onClick={executeRunbook} disabled={running}>{running ? 'Running...' : 'Execute Runbook'}</button>
        </div>
      </div>
      <div className="card">
        <h3>Target Hosts ({scopedHosts.length})</h3>
        {scopedHosts.length === 0 ? <p className="text-muted">No hosts in selected channel.</p> : (
          <table className="table">
            <thead><tr><th style={{width:60}}>Use</th><th>Host</th><th>IP</th><th>OS</th></tr></thead>
            <tbody>
              {scopedHosts.map(h => (
                <tr key={`runbook-host-${h.id}`}>
                  <td><input type="checkbox" checked={selectedHostIds.includes(String(h.id))} onChange={()=>setSelectedHostIds(prev => prev.includes(String(h.id)) ? prev.filter(x => x !== String(h.id)) : [...prev, String(h.id)])} /></td>
                  <td>{h.hostname || h.name}</td>
                  <td>{h.ip}</td>
                  <td>{h.os || 'Unknown'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h3>Local Repository Packages ({packages.length})</h3>
        {packages.length === 0 ? <p className="text-muted">No packages available in local repository.</p> : (
          <table className="table">
            <thead><tr><th style={{width:60}}>Use</th><th>Name</th><th>Size</th></tr></thead>
            <tbody>
              {packages.slice(0, 150).map(p => (
                <tr key={`runbook-pkg-${p.name}`}>
                  <td><input type="checkbox" checked={selectedFiles.includes(p.name)} onChange={()=>setSelectedFiles(prev => prev.includes(p.name) ? prev.filter(x => x !== p.name) : [...prev, p.name])} /></td>
                  <td>{p.name}</td>
                  <td>{p.size_mb} MB</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h3>Runbook Steps</h3>
        <table className="table">
          <thead><tr><th>Step</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {steps.map(s => (
              <tr key={s.key}>
                <td>{s.label}</td>
                <td>{s.status === 'success' ? <span className="badge badge-success">success</span> : s.status === 'failed' ? <span className="badge badge-danger">failed</span> : s.status === 'running' ? <span className="badge badge-info">running</span> : <span className="badge badge-warning">pending</span>}</td>
                <td>{s.detail || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h3>Execution Log</h3>
        {runbookLog.length === 0 ? <p className="text-muted">No run executed yet.</p> : <pre className="code-block">{runbookLog.join('\n')}</pre>}
      </div>
      <div className="card">
        <h3>Runbook Execution History</h3>
        {serverRuns.length === 0 ? <p className="text-muted">No execution history available.</p> : (
          <table className="table">
            <thead><tr><th>ID</th><th>Status</th><th>Trigger</th><th>Started</th><th>Completed</th><th>Audit</th></tr></thead>
            <tbody>
              {serverRuns.map(run => (
                <tr key={`runbook-run-${run.id}`}>
                  <td>#{run.id}</td>
                  <td>{run.status === 'success' ? <span className="badge badge-success">success</span> : run.status === 'failed' ? <span className="badge badge-danger">failed</span> : <span className="badge badge-info">{run.status}</span>}</td>
                  <td>{run.trigger_type}</td>
                  <td>{run.started_at ? new Date(run.started_at).toLocaleString() : '-'}</td>
                  <td>{run.completed_at ? new Date(run.completed_at).toLocaleString() : '-'}</td>
                  <td style={{display:'flex',gap:6}}>
                    <button className="btn btn-sm btn-secondary" onClick={()=>downloadRunAudit(run.id, 'csv')}>CSV</button>
                    <button className="btn btn-sm btn-secondary" onClick={()=>downloadRunAudit(run.id, 'pdf')}>PDF</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
