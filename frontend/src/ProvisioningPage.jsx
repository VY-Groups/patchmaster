import React, { useEffect, useMemo, useState } from 'react';
import './OpsPages.css';
import { AppIcon } from './AppIcons';

function formatBytes(value) {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return '-';
  if (size >= 1024 ** 3) return `${(size / 1024 ** 3).toFixed(2)} GB`;
  if (size >= 1024 ** 2) return `${(size / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.round(size / 1024)} KB`;
}

function osFamily(host) {
  const value = String(host?.os || '').toLowerCase();
  if (value.includes('win')) return 'windows';
  if (value) return 'linux';
  return 'unknown';
}

export default function ProvisioningPage({ hosts, API, apiFetch, useInterval }) {
  const [templates, setTemplates] = useState([]);
  const [runs, setRuns] = useState([]);
  const [sourceHostId, setSourceHostId] = useState('');
  const [sourceSnapshots, setSourceSnapshots] = useState([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [captureForm, setCaptureForm] = useState({
    name: '',
    snapshot_name: '',
    description: '',
    labels: '',
    site_scope: '',
  });
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [selectedTargetIds, setSelectedTargetIds] = useState([]);
  const [allowCrossSite, setAllowCrossSite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  // Defensive array checks
  const safeHosts = Array.isArray(hosts) ? hosts : [];
  const safeTemplates = Array.isArray(templates) ? templates : [];
  const safeRuns = Array.isArray(runs) ? runs : [];
  const safeSourceSnapshots = Array.isArray(sourceSnapshots) ? sourceSnapshots : [];

  const selectedSourceHost = useMemo(
    () => safeHosts.find((host) => String(host.id) === String(sourceHostId)),
    [safeHosts, sourceHostId]
  );
  const selectedTemplate = useMemo(
    () => safeTemplates.find((template) => String(template.id) === String(selectedTemplateId)),
    [safeTemplates, selectedTemplateId]
  );

  const refreshTemplates = async () => {
    try {
      const response = await apiFetch(`${API}/api/provisioning/templates`);
      const payload = await response.json();
      setTemplates(payload.items || []);
      setSelectedTemplateId((current) => {
        if (current && (payload.items || []).some((item) => String(item.id) === String(current))) {
          return current;
        }
        return String(payload.items?.[0]?.id || '');
      });
    } catch {
      setTemplates([]);
    }
  };

  const refreshRuns = async () => {
    try {
      const response = await apiFetch(`${API}/api/provisioning/runs`);
      const payload = await response.json();
      setRuns(payload.items || []);
    } catch {
      setRuns([]);
    }
  };

  const refreshSnapshots = async (hostId) => {
    if (!hostId) {
      setSourceSnapshots([]);
      return;
    }
    setLoadingSnapshots(true);
    try {
      const response = await apiFetch(`${API}/api/agent/by-host/${hostId}/snapshot/list`);
      const payload = await response.json();
      const items = Array.isArray(payload.snapshots) ? payload.snapshots : [];
      const sorted = items
        .filter((item) => String(item.mode || '').toLowerCase() === 'full_system')
        .sort((a, b) => String(b.created || '').localeCompare(String(a.created || '')));
      setSourceSnapshots(sorted);
      setCaptureForm((current) => ({
        ...current,
        snapshot_name: current.snapshot_name && sorted.some((item) => item.name === current.snapshot_name)
          ? current.snapshot_name
          : String(sorted[0]?.name || ''),
      }));
    } catch {
      setSourceSnapshots([]);
    } finally {
      setLoadingSnapshots(false);
    }
  };

  useEffect(() => {
    refreshTemplates();
    refreshRuns();
  }, []);

  useEffect(() => {
    refreshSnapshots(sourceHostId);
  }, [sourceHostId]);

  useInterval(() => {
    refreshRuns();
  }, 5000);

  const matchingTargets = useMemo(() => {
    if (!selectedTemplate) return safeHosts;
    return safeHosts.filter((host) => {
      if (selectedTemplate.source_host?.id && host.id === selectedTemplate.source_host.id) return false;
      const familyOk = !selectedTemplate.os_family || selectedTemplate.os_family === 'unknown' || osFamily(host) === selectedTemplate.os_family;
      if (!familyOk) return false;
      if (!allowCrossSite && selectedTemplate.site_scope && host.site && host.site !== selectedTemplate.site_scope) return false;
      return true;
    });
  }, [allowCrossSite, safeHosts, selectedTemplate]);

  const captureTemplate = async () => {
    if (!sourceHostId || !captureForm.name.trim() || !captureForm.snapshot_name.trim()) {
      setNotice('Choose a source host, template name, and snapshot first.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/provisioning/templates/capture`, {
        method: 'POST',
        body: JSON.stringify({
          host_id: Number(sourceHostId),
          name: captureForm.name.trim(),
          snapshot_name: captureForm.snapshot_name.trim(),
          description: captureForm.description.trim(),
          labels: captureForm.labels.split(',').map((item) => item.trim()).filter(Boolean),
          site_scope: captureForm.site_scope.trim(),
          snapshot_mode: 'full_system',
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not capture provisioning template.');
        return;
      }
      setNotice(`Provisioning template "${payload.name}" captured and stored on the Patch-SecOps Solution server.`);
      setCaptureForm({ name: '', snapshot_name: '', description: '', labels: '', site_scope: selectedSourceHost?.site || '' });
      await refreshTemplates();
      setSelectedTemplateId(String(payload.id));
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const launchRollout = async () => {
    if (!selectedTemplateId || selectedTargetIds.length === 0) {
      setNotice('Pick a template and at least one target host.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/provisioning/runs`, {
        method: 'POST',
        body: JSON.stringify({
          template_id: Number(selectedTemplateId),
          target_host_ids: selectedTargetIds.map((value) => Number(value)),
          allow_cross_site: allowCrossSite,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not start provisioning rollout.');
        return;
      }
      setNotice(`Provisioning rollout queued. Queue job: ${payload.job?.id || 'pending'}.`);
      setSelectedTargetIds([]);
      await refreshRuns();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const selectMatchingTargets = () => {
    setSelectedTargetIds(matchingTargets.map((host) => host.id));
  };

  const toggleTarget = (hostId) => {
    setSelectedTargetIds((current) => (
      current.includes(hostId) ? current.filter((value) => value !== hostId) : [...current, hostId]
    ));
  };

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#bfdbfe', background: 'linear-gradient(145deg, #eef6ff, #f8fbff)' }}>
          <div className="ops-kicker">Provisioning center</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Workflow</span>
              <span className="ops-emphasis-value" style={{ color: '#1d4ed8', fontSize: 26 }}>Golden Image</span>
              <span className="ops-emphasis-meta">Capture once from a validated source host, then roll the stored image to matching targets through the ops queue.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Automate recovery-grade OS provisioning with reusable image templates.</h3>
              <p>
                This workspace turns the existing snapshot and full-system image engine into a repeatable rollout flow. Operators capture a known-good source image, store it on the Patch-SecOps Solution server, and reimage selected hosts without hand-moving archives between machines.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">Stored image catalog</span>
            <span className="ops-chip">Queued rollouts</span>
            <span className="ops-chip">OS and site guardrails</span>
            <span className="ops-chip">Target-by-target results</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Current scope</span>
          <div className="ops-side-metric">Agent-led</div>
          <p className="ops-side-note">
            This is production-ready image capture and rollout for registered agents. It is ideal for lab rebuilds, branch refreshes, recovery cutovers, and standardized golden-image redeployments.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>{safeTemplates.length}</strong>
              <span>stored templates</span>
            </div>
            <div className="ops-inline-card">
              <strong>{safeRuns.length}</strong>
              <span>tracked runs</span>
            </div>
            <div className="ops-inline-card">
              <strong>{safeHosts.length}</strong>
              <span>available hosts</span>
            </div>
            <div className="ops-inline-card">
              <strong>{selectedTargetIds.length}</strong>
              <span>selected targets</span>
            </div>
          </div>
        </div>
      </div>

      {notice ? (
        <div className="ops-panel" style={{ borderColor: '#cbd5e1', background: 'linear-gradient(180deg, #ffffff, #f8fafc)' }}>
          <div className="ops-panel-title" style={{ fontSize: 15 }}>Status</div>
          <p className="ops-subtle" style={{ marginTop: 8 }}>{notice}</p>
        </div>
      ) : null}

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">1. Capture a provisioning template</div>
              <p className="ops-subtle">Choose a source host, select one of its exported snapshots, and store the archive on the Patch-SecOps Solution server as a reusable golden image.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <div>
              <label className="ops-side-label">Source host</label>
              <select className="input" value={sourceHostId} onChange={(event) => {
                const nextHostId = event.target.value;
                setSourceHostId(nextHostId);
                const nextHost = safeHosts.find((host) => String(host.id) === String(nextHostId));
                setCaptureForm((current) => ({ ...current, site_scope: nextHost?.site || '' }));
              }}>
                <option value="">Select host</option>
                {safeHosts.map((host) => (
                  <option key={host.id} value={host.id}>
                    {host.hostname} ({host.ip}){host.site ? ` - ${host.site}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">Stored snapshot</label>
              <select className="input" value={captureForm.snapshot_name} onChange={(event) => setCaptureForm((current) => ({ ...current, snapshot_name: event.target.value }))}>
                <option value="">{loadingSnapshots ? 'Loading snapshots...' : 'Select snapshot'}</option>
                {safeSourceSnapshots.map((snapshot) => (
                  <option key={snapshot.name} value={snapshot.name}>
                    {snapshot.name} ({snapshot.mode || 'packages'}){snapshot.created ? ` - ${snapshot.created}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">Template name</label>
              <input className="input" value={captureForm.name} onChange={(event) => setCaptureForm((current) => ({ ...current, name: event.target.value }))} placeholder="Windows-11-Branch-Golden-April" />
            </div>
            <div>
              <label className="ops-side-label">Site scope</label>
              <input className="input" value={captureForm.site_scope} onChange={(event) => setCaptureForm((current) => ({ ...current, site_scope: event.target.value }))} placeholder="Optional site guardrail" />
            </div>
          </div>
          <div className="ops-form-grid" style={{ marginTop: 12 }}>
            <div>
              <label className="ops-side-label">Labels</label>
              <input className="input" value={captureForm.labels} onChange={(event) => setCaptureForm((current) => ({ ...current, labels: event.target.value }))} placeholder="golden, branch, windows-11" />
            </div>
            <div>
              <label className="ops-side-label">Description</label>
              <input className="input" value={captureForm.description} onChange={(event) => setCaptureForm((current) => ({ ...current, description: event.target.value }))} placeholder="Validated branch desktop baseline with approved software set" />
            </div>
          </div>
          {selectedSourceHost ? (
            <div className="ops-detail-grid">
              <div className="ops-detail-item">
                <span>Source OS</span>
                <strong>{selectedSourceHost.os || 'Unknown'} {selectedSourceHost.os_version || ''}</strong>
              </div>
              <div className="ops-detail-item">
                <span>Source site</span>
                <strong>{selectedSourceHost.site || 'No site assigned'}</strong>
              </div>
            </div>
          ) : null}
          <div className="ops-actions">
            <button className="btn btn-primary" disabled={busy} onClick={captureTemplate}>
              {busy ? 'Capturing...' : 'Capture template'}
            </button>
            <button className="btn btn-sm" onClick={() => refreshSnapshots(sourceHostId)} disabled={!sourceHostId || loadingSnapshots}>
              {loadingSnapshots ? 'Refreshing...' : 'Refresh snapshots'}
            </button>
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">2. Launch a provisioning rollout</div>
              <p className="ops-subtle">Pick a stored template, review the eligible targets, then queue a reimage run. Guardrails prevent accidental cross-site or cross-platform rollouts unless you explicitly allow them.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <div>
              <label className="ops-side-label">Template</label>
              <select className="input" value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)}>
                <option value="">Select template</option>
                {safeTemplates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} ({template.os_family || 'unknown'}){template.site_scope ? ` - ${template.site_scope}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="ops-toggle-option" style={{ minHeight: 54 }}>
              <input id="allow-cross-site" type="checkbox" checked={allowCrossSite} onChange={(event) => setAllowCrossSite(event.target.checked)} />
              <div className="ops-toggle-copy">
                <strong>Allow cross-site rollout</strong>
                <span>Disable this for safer branch-by-branch golden image reuse. Enable it only when the same image is approved across sites.</span>
              </div>
            </div>
          </div>
          {selectedTemplate ? (
            <div className="ops-detail-grid">
              <div className="ops-detail-item">
                <span>Stored archive</span>
                <strong>{selectedTemplate.archive_present ? `${formatBytes(selectedTemplate.archive_size_bytes)} ready` : 'Missing from server storage'}</strong>
              </div>
              <div className="ops-detail-item">
                <span>Source host</span>
                <strong>{selectedTemplate.source_host?.hostname || 'Archived source'}{selectedTemplate.source_host?.site ? ` - ${selectedTemplate.source_host.site}` : ''}</strong>
              </div>
            </div>
          ) : null}
          <div className="ops-table-toolbar" style={{ marginTop: 16 }}>
            <div>
              <div className="ops-panel-title" style={{ fontSize: 16 }}>Target hosts</div>
              <p className="ops-subtle">Only hosts matching the selected template&apos;s OS family and site scope are pre-filtered here.</p>
            </div>
            <div className="ops-actions">
              <button className="btn btn-sm" onClick={selectMatchingTargets}>Select filtered</button>
              <button className="btn btn-sm" onClick={() => setSelectedTargetIds([])}>Clear</button>
            </div>
          </div>
          <div className="ops-list" style={{ maxHeight: 320, overflow: 'auto' }}>
            {matchingTargets.length === 0 ? (
              <div className="ops-empty">No eligible targets for the current template and site guardrails.</div>
            ) : matchingTargets.map((host) => (
              <label key={host.id} className="ops-toggle-option">
                <input type="checkbox" checked={selectedTargetIds.includes(host.id)} onChange={() => toggleTarget(host.id)} />
                <div className="ops-toggle-copy">
                  <strong>{host.hostname}</strong>
                  <span>{host.ip} | {host.os || 'Unknown OS'}{host.site ? ` | ${host.site}` : ''}{host.is_online ? '' : ' | offline'}</span>
                </div>
              </label>
            ))}
          </div>
          <div className="ops-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" disabled={busy || !selectedTemplateId} onClick={launchRollout}>
              {busy ? 'Queueing...' : 'Queue rollout'}
            </button>
            <span className="ops-subtle">{selectedTargetIds.length} target{selectedTargetIds.length === 1 ? '' : 's'} selected</span>
          </div>
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Provisioning templates</div>
            <p className="ops-subtle">These are the stored golden images currently held on the Patch-SecOps Solution server.</p>
          </div>
          <button className="btn btn-sm" onClick={refreshTemplates}>Refresh templates</button>
        </div>
        {safeTemplates.length === 0 ? (
          <div className="ops-empty">No provisioning templates yet. Capture one from a validated source host snapshot to start image-based rollout.</div>
        ) : (
          <table className="table ops-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th>Scope</th>
                <th>Archive</th>
                <th>Labels</th>
              </tr>
            </thead>
            <tbody>
              {safeTemplates.map((template) => (
                <tr key={template.id}>
                  <td>
                    <strong>{template.name}</strong>
                    <span className="ops-table-meta">{template.description || 'No description set.'}</span>
                  </td>
                  <td>
                    {template.source_host?.hostname || 'Archived'}
                    <span className="ops-table-meta">{template.source_snapshot_name}</span>
                  </td>
                  <td>
                    <span className="badge badge-info" style={{ marginRight: 6 }}>{template.os_family || 'unknown'}</span>
                    <span className="badge badge-secondary">{template.site_scope || 'global'}</span>
                  </td>
                  <td>
                    <span className={`badge ${template.archive_present ? 'badge-success' : 'badge-danger'}`}>{template.archive_present ? 'stored' : 'missing'}</span>
                    <span className="ops-table-meta">{formatBytes(template.archive_size_bytes)}</span>
                  </td>
                  <td>
                    <div className="ops-tag-row">
                      {(template.labels || []).length > 0 ? template.labels.map((label) => (
                        <span key={label} className="badge badge-light">{label}</span>
                      )) : <span className="ops-table-meta">No labels</span>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Provisioning run history</div>
            <p className="ops-subtle">Each queued rollout records target-by-target results so operators can prove what ran, what failed, and what needs follow-up.</p>
          </div>
          <button className="btn btn-sm" onClick={refreshRuns}>Refresh runs</button>
        </div>
        {safeRuns.length === 0 ? (
          <div className="ops-empty">No provisioning runs yet.</div>
        ) : (
          <table className="table ops-table">
            <thead>
              <tr>
                <th>Template</th>
                <th>Status</th>
                <th>Targets</th>
                <th>Queue</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {safeRuns.map((run) => (
                <tr key={run.id}>
                  <td>
                    <strong>{run.template?.name || `Run ${run.id}`}</strong>
                    <span className="ops-table-meta">By {run.initiated_by || 'system'} on {run.created_at ? new Date(run.created_at).toLocaleString() : '-'}</span>
                  </td>
                  <td>
                    <span className={`badge ${run.status === 'success' ? 'badge-success' : run.status === 'partial_success' ? 'badge-warning' : run.status === 'failed' ? 'badge-danger' : 'badge-info'}`}>
                      {run.status}
                    </span>
                  </td>
                  <td>
                    {run.result_summary?.total_targets ?? run.target_host_ids?.length ?? 0}
                    <span className="ops-table-meta">
                      {run.result_summary?.success_count ?? 0} success / {run.result_summary?.failed_count ?? 0} failed
                    </span>
                  </td>
                  <td>
                    <span className="badge badge-light">{run.queue_job_id || 'n/a'}</span>
                  </td>
                  <td>
                    <details>
                      <summary style={{ cursor: 'pointer', color: '#1d4ed8' }}>View target results</summary>
                      <pre className="ops-console">{JSON.stringify(run.result_summary || {}, null, 2)}</pre>
                    </details>
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
