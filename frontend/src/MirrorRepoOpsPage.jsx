import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

const providers = [
  { value: 'ubuntu', label: 'Ubuntu' },
  { value: 'redhat', label: 'Red Hat' },
  { value: 'microsoft', label: 'Microsoft' },
  { value: 'custom', label: 'Custom Feed' },
];

const osFamilies = [
  { value: 'linux', label: 'Linux' },
  { value: 'windows', label: 'Windows' },
];

const providerDefaultSources = {
  ubuntu: 'https://ubuntu.com/security/notices.json',
  redhat: 'https://access.redhat.com/hydra/rest/securitydata/csaf.json',
  microsoft: 'https://api.msrc.microsoft.com/cvrf/v3.0/updates',
};

function defaultForm() {
  return {
    name: '',
    provider: 'ubuntu',
    os_family: 'linux',
    channel: 'default',
    source_url: '',
    enabled: true,
    metadata_only: true,
    sync_interval_minutes: 360,
    retention_days: 30,
    keep_versions: 2,
  };
}

export default function MirrorRepoOpsPage({ API, apiFetch, AppIcon }) {
  const [repos, setRepos] = useState([]);
  const [hosts, setHosts] = useState([]);
  const [selectedRepoId, setSelectedRepoId] = useState(null);
  const [runs, setRuns] = useState([]);
  const [packages, setPackages] = useState([]);
  const [compareRows, setCompareRows] = useState([]);
  const [compareTotals, setCompareTotals] = useState(null);
  const [compareError, setCompareError] = useState('');
  const [compareHostId, setCompareHostId] = useState('');
  const [retentionPreview, setRetentionPreview] = useState([]);
  const [retentionPreviewTotal, setRetentionPreviewTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const [lastRefreshAt, setLastRefreshAt] = useState('');
  const [deleteDiagnostics, setDeleteDiagnostics] = useState(null);
  const [showDeleteDiagnostics, setShowDeleteDiagnostics] = useState(false);
  const [query, setQuery] = useState('');
  const [createMode, setCreateMode] = useState(false);
  const [form, setForm] = useState(defaultForm);

  const selectedRepo = useMemo(
    () => repos.find((repo) => repo.id === selectedRepoId) || null,
    [repos, selectedRepoId],
  );
  const createDefaultSource = providerDefaultSources[form.provider] || '';
  const selectedDefaultSource = providerDefaultSources[selectedRepo?.provider] || '';
  const isSatelliteRepo = selectedRepo && String(selectedRepo?.extra_config?.feed_family || '').toLowerCase() === 'satellite';

  const patchSelectedRepo = (mutate) => {
    if (!selectedRepo) return;
    setRepos((prev) => prev.map((repo) => (repo.id === selectedRepo.id ? mutate(repo) : repo)));
  };

  const parseApiError = async (response, fallback) => {
    const statusText = `${response.status} ${response.statusText || ''}`.trim();
    let detail = '';
    try {
      const payload = await response.clone().json();
      detail = String(payload?.detail || payload?.error || payload?.message || '').trim();
      if (!detail && payload && typeof payload === 'object') {
        detail = JSON.stringify(payload);
      }
    } catch {
      try {
        detail = (await response.clone().text()).trim();
      } catch {
        detail = '';
      }
    }
    return detail ? `${fallback} (${statusText}): ${detail}` : `${fallback} (${statusText})`;
  };

  const loadRepos = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiFetch(`${API}/api/mirror/repos?ts=${Date.now()}`);
      const payload = await response.json();
      const list = Array.isArray(payload) ? payload : [];
      setRepos(list);
      if (!selectedRepoId && list.length) {
        setSelectedRepoId(list[0].id);
      } else if (selectedRepoId && !list.find((item) => item.id === selectedRepoId)) {
        setSelectedRepoId(list.length ? list[0].id : null);
      }
    } catch (error) {
      setMessage(`Unable to load mirror repositories: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }, [API, apiFetch, selectedRepoId]);

  const loadHosts = useCallback(async () => {
    try {
      const response = await apiFetch(`${API}/api/hosts/?ts=${Date.now()}`);
      const payload = await response.json();
      const list = Array.isArray(payload) ? payload : (Array.isArray(payload?.items) ? payload.items : []);
      setHosts(list);
      if (!compareHostId && list.length) {
        setCompareHostId(String(list[0].id));
      }
    } catch (error) {
      setMessage(`Unable to load hosts for comparison: ${error.message}`);
    }
  }, [API, apiFetch, compareHostId]);

  const loadRepoData = useCallback(async () => {
    if (!selectedRepoId) {
      setRuns([]);
      setPackages([]);
      return;
    }
    try {
      const [runsResp, pkgResp] = await Promise.all([
        apiFetch(`${API}/api/mirror/repos/${selectedRepoId}/runs?limit=20&ts=${Date.now()}`),
        apiFetch(`${API}/api/mirror/repos/${selectedRepoId}/packages?limit=50&q=${encodeURIComponent(query)}&ts=${Date.now()}`),
      ]);
      const runsPayload = await runsResp.json();
      const pkgPayload = await pkgResp.json();
      setRuns(Array.isArray(runsPayload) ? runsPayload : []);
      setPackages(Array.isArray(pkgPayload?.items) ? pkgPayload.items : []);
    } catch (error) {
      setMessage(`Unable to load selected repository data: ${error.message}`);
    }
  }, [API, apiFetch, query, selectedRepoId]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadRepos(), loadHosts()]);
    await loadRepoData();
    setLastRefreshAt(new Date().toLocaleTimeString());
  }, [loadHosts, loadRepoData, loadRepos]);

  useEffect(() => {
    loadRepos();
  }, [loadRepos]);

  useEffect(() => {
    loadHosts();
  }, [loadHosts]);

  useEffect(() => {
    loadRepoData();
  }, [loadRepoData]);

  useEffect(() => {
    const id = setInterval(() => {
      refreshAll();
    }, 8000);
    return () => clearInterval(id);
  }, [refreshAll]);

  const runCompare = useCallback(async () => {
    if (!selectedRepo || !compareHostId) return;
    setActionLoading(true);
    setCompareError('');
    setErrorDetail('');
    try {
      const response = await apiFetch(
        `${API}/api/mirror/compare/host/${compareHostId}?repo_id=${selectedRepo.id}&q=${encodeURIComponent(query)}&limit=200`,
      );
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Compare failed'));
      }
      const payload = await response.json();
      setCompareRows(Array.isArray(payload?.items) ? payload.items : []);
      setCompareTotals(payload?.totals || null);
      if (payload?.agent_fetch_error) {
        setCompareError(`Agent package query warning: ${payload.agent_fetch_error}`);
      }
    } catch (error) {
      setCompareRows([]);
      setCompareTotals(null);
      setCompareError(error.message);
    } finally {
      setActionLoading(false);
    }
  }, [API, apiFetch, compareHostId, query, selectedRepo]);

  const createRepo = async () => {
    if (!form.name.trim()) {
      setMessage('Repository name is required.');
      return;
    }
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos`, {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          sync_interval_minutes: Number(form.sync_interval_minutes),
          retention_days: Number(form.retention_days),
          keep_versions: Number(form.keep_versions),
        }),
      });
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Create failed'));
      }
      const payload = await response.json();
      setCreateMode(false);
      setForm(defaultForm());
      setMessage('Mirror repository created.');
      await refreshAll();
      if (payload?.id) {
        setSelectedRepoId(payload.id);
      }
    } catch (error) {
      setMessage(`Create failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const updateRepo = async () => {
    if (!selectedRepo) return;
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos/${selectedRepo.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          provider: selectedRepo.provider,
          os_family: selectedRepo.os_family,
          channel: selectedRepo.channel,
          source_url: selectedRepo.source_url,
          enabled: selectedRepo.enabled,
          metadata_only: selectedRepo.metadata_only,
          sync_interval_minutes: Number(selectedRepo.sync_interval_minutes),
          retention_days: Number(selectedRepo.retention_days),
          keep_versions: Number(selectedRepo.keep_versions),
          ...(selectedRepo?.auth_config?.token?.trim()
            ? { auth_config: { ...(selectedRepo.auth_config || {}), token: selectedRepo.auth_config.token.trim() } }
            : {}),
          extra_config: selectedRepo.extra_config || {},
        }),
      });
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Update failed'));
      }
      setMessage('Repository settings saved.');
      await refreshAll();
    } catch (error) {
      setMessage(`Update failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const runSync = async () => {
    if (!selectedRepo) return;
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos/${selectedRepo.id}/sync`, { method: 'POST' });
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Sync failed'));
      }
      const payload = await response.json().catch(() => ({}));
      if (payload?.job?.id) {
        window.dispatchEvent(new CustomEvent('pm-open-ops-queue', { detail: { jobId: payload.job.id } }));
      }
      if (payload?.status === 'accepted' || payload?.summary?.reason === 'started_in_background') {
        setMessage('Sync started in background. Check latest sync runs and refresh details.');
      } else
      if (payload?.summary?.status === 'skipped' && payload?.summary?.reason === 'sync_in_progress') {
        setMessage('Sync skipped: repository is already syncing.');
      } else if (payload?.summary?.status === 'skipped' && payload?.summary?.reason === 'sync_locked_by_other_node') {
        const lease = payload?.summary?.lease || {};
        const owner = lease.holder_node || lease.holder_id || 'another backend node';
        setMessage(`Sync skipped: distributed lock held by ${owner}.`);
      } else if (payload?.summary?.delta_skipped) {
        setMessage('Sync completed: no source changes since last checkpoint (delta skip).');
      } else {
        setMessage('Sync completed.');
      }
      await refreshAll();
    } catch (error) {
      await refreshAll();
      setMessage(`Sync request interrupted: ${error.message}. Check "Latest sync runs" for background status.`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const runRetention = async () => {
    if (!selectedRepo) return;
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos/${selectedRepo.id}/retention`, { method: 'POST' });
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Retention failed'));
      }
      const payload = await response.json().catch(() => ({}));
      if (payload?.job?.id) {
        window.dispatchEvent(new CustomEvent('pm-open-ops-queue', { detail: { jobId: payload.job.id } }));
        setMessage('Retention queued. Redirecting focus to Operations Queue.');
      } else {
        setMessage('Retention run completed.');
      }
      await loadRepoData();
    } catch (error) {
      setMessage(`Retention failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const previewRetention = async () => {
    if (!selectedRepo) return;
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos/${selectedRepo.id}/retention/preview?limit=100`);
      if (!response.ok) {
        throw new Error(await parseApiError(response, 'Retention preview failed'));
      }
      const payload = await response.json();
      const summary = payload?.summary || {};
      setRetentionPreview(Array.isArray(summary.preview) ? summary.preview : []);
      setRetentionPreviewTotal(Number(summary.would_remove_packages || 0));
      setMessage(`Retention preview ready: ${Number(summary.would_remove_packages || 0)} package versions would be removed.`);
    } catch (error) {
      setRetentionPreview([]);
      setRetentionPreviewTotal(0);
      setMessage(`Retention preview failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const removeRepo = async () => {
    if (!selectedRepo) return;
    if (!window.confirm(`Delete mirror repository "${selectedRepo.name}"?`)) return;
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/repos/${selectedRepo.id}`, { method: 'DELETE' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = payload?.detail && typeof payload.detail === 'object' ? payload.detail : payload;
        const diagnostics = {
          message: String(detail?.message || detail?.detail || 'Delete failed'),
          reason: String(detail?.reason || ''),
          status: response.status,
          status_text: response.statusText || '',
          request_id: String(detail?.request_id || response.headers.get('x-request-id') || ''),
          trace_token: String(detail?.trace_token || response.headers.get('x-trace-token') || ''),
          repo_id: selectedRepo.id,
          repo_name: selectedRepo.name,
          timestamp: new Date().toISOString(),
        };
        setDeleteDiagnostics(diagnostics);
        setShowDeleteDiagnostics(true);
        throw new Error(`${diagnostics.message} (${diagnostics.status} ${diagnostics.status_text})`);
      }
      setMessage('Repository deleted.');
      setDeleteDiagnostics(null);
      setShowDeleteDiagnostics(false);
      setSelectedRepoId(null);
      await refreshAll();
    } catch (error) {
      setMessage(`Delete failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  const autoBootstrapAndSync = async () => {
    setActionLoading(true);
    setMessage('');
    setErrorDetail('');
    try {
      const response = await apiFetch(`${API}/api/mirror/automation/bootstrap-sync?online_only=true&max_hosts=500`, { method: 'POST' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || `Automation start failed (${response.status})`);
      }
      setMessage(`Automation started: scheduled ${payload.scheduled || 0} host-derived sync bootstrap task(s), skipped ${payload.skipped || 0}.`);
      await refreshAll();
    } catch (error) {
      setMessage(`Automation failed: ${error.message}`);
      setErrorDetail(String(error?.stack || error?.message || error));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="ops-shell">
      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Mirror Repositories</div>
            <p className="ops-subtle">Complete mirror service: source channels, sync schedule, catalog index, retention rules, and relay-ready package metadata.</p>
          </div>
          <div className="ops-actions">
            <button className="btn btn-sm" onClick={refreshAll} disabled={loading || actionLoading}>Refresh</button>
            <button className="btn btn-sm" onClick={autoBootstrapAndSync} disabled={loading || actionLoading}>Auto Bootstrap + Sync</button>
            <button className="btn btn-primary" onClick={() => setCreateMode((v) => !v)} disabled={actionLoading}>
              {createMode ? 'Cancel' : 'Add Repository'}
            </button>
          </div>
        </div>

        {message && <div className="ops-command-card" style={{ marginBottom: 12 }}>{message}</div>}
        {lastRefreshAt && <div className="ops-subtle" style={{ marginBottom: 8 }}>Last refreshed: {lastRefreshAt}</div>}
        {errorDetail && (
          <div className="ops-command-card" style={{ marginBottom: 12, border: '1px solid rgba(220,38,38,0.35)' }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Operation error details</div>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{errorDetail}</pre>
            <div style={{ marginTop: 10 }}>
              <button className="btn btn-sm" type="button" onClick={() => navigator.clipboard?.writeText(errorDetail)}>Copy Error</button>
              {deleteDiagnostics ? (
                <button className="btn btn-sm" type="button" style={{ marginLeft: 8 }} onClick={() => setShowDeleteDiagnostics(true)}>
                  Open Delete Diagnostics
                </button>
              ) : null}
            </div>
          </div>
        )}

        {createMode && (
          <div className="ops-form-grid" style={{ marginBottom: 14 }}>
            <input className="input" placeholder="Repository name" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
            <select
              className="input"
              value={form.provider}
              onChange={(e) =>
                setForm((prev) => {
                  const nextProvider = e.target.value;
                  const prevDefault = providerDefaultSources[prev.provider] || '';
                  const nextDefault = providerDefaultSources[nextProvider] || '';
                  const shouldSwapDefault = !prev.source_url || prev.source_url === prevDefault;
                  return {
                    ...prev,
                    provider: nextProvider,
                    source_url: shouldSwapDefault ? nextDefault : prev.source_url,
                  };
                })
              }
            >
              {providers.map((provider) => <option key={provider.value} value={provider.value}>{provider.label}</option>)}
            </select>
            <select className="input" value={form.os_family} onChange={(e) => setForm((prev) => ({ ...prev, os_family: e.target.value }))}>
              {osFamilies.map((osFamily) => <option key={osFamily.value} value={osFamily.value}>{osFamily.label}</option>)}
            </select>
            <input className="input" placeholder="Channel (prod, n-1, delayed, etc.)" value={form.channel} onChange={(e) => setForm((prev) => ({ ...prev, channel: e.target.value }))} />
            <input className="input" placeholder="Source URL (optional for vendor defaults)" value={form.source_url} onChange={(e) => setForm((prev) => ({ ...prev, source_url: e.target.value }))} />
            <input className="input" type="number" min="5" value={form.sync_interval_minutes} onChange={(e) => setForm((prev) => ({ ...prev, sync_interval_minutes: e.target.value }))} />
            <input className="input" type="number" min="1" value={form.retention_days} onChange={(e) => setForm((prev) => ({ ...prev, retention_days: e.target.value }))} />
            <input className="input" type="number" min="1" value={form.keep_versions} onChange={(e) => setForm((prev) => ({ ...prev, keep_versions: e.target.value }))} />
            <label className="toggle-option"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm((prev) => ({ ...prev, enabled: e.target.checked }))} /> Enabled</label>
            <label className="toggle-option"><input type="checkbox" checked={form.metadata_only} onChange={(e) => setForm((prev) => ({ ...prev, metadata_only: e.target.checked }))} /> Metadata only</label>
            <div className="ops-subtle" style={{ gridColumn: '1 / -1' }}>
              Preconfigured sources:
              {' '}Ubuntu ({providerDefaultSources.ubuntu}) ·
              {' '}Red Hat ({providerDefaultSources.redhat}) ·
              {' '}Windows/Microsoft ({providerDefaultSources.microsoft}).
              {' '}Debian can be added via Custom Feed URL.
              {createDefaultSource ? (
                <>
                  {' '}Current provider default:
                  {' '}<button className="btn btn-sm" type="button" onClick={() => setForm((prev) => ({ ...prev, source_url: createDefaultSource }))}>
                    Use {form.provider} default
                  </button>
                </>
              ) : null}
            </div>
            <button className="btn btn-success" onClick={createRepo} disabled={actionLoading}>Create</button>
          </div>
        )}

        {loading && !repos.length ? (
          <div className="ops-empty">Loading mirror repositories...</div>
        ) : !repos.length ? (
          <div className="ops-empty">No mirror repositories configured yet.</div>
        ) : (
          <table className="table ops-table" style={{ marginBottom: 12 }}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Provider</th>
                <th>OS</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Catalog</th>
                <th>Last sync</th>
              </tr>
            </thead>
            <tbody>
              {repos.map((repo) => (
                <tr key={repo.id} onClick={() => setSelectedRepoId(repo.id)} style={{ cursor: 'pointer', background: selectedRepoId === repo.id ? 'rgba(37,99,235,0.08)' : undefined }}>
                  <td><strong>{repo.name}</strong></td>
                  <td>{repo.provider}</td>
                  <td>{repo.os_family}</td>
                  <td>{repo.channel}</td>
                  <td><span className={`badge ${repo.enabled ? 'badge-success' : 'badge-secondary'}`}>{repo.enabled ? 'enabled' : 'disabled'}</span></td>
                  <td>{repo.last_sync_summary?.items_seen ?? 0}</td>
                  <td>{repo.last_sync_at ? new Date(repo.last_sync_at).toLocaleString() : 'Never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedRepo && (
        <div className="grid-2">
          <div className="ops-panel">
            <div className="ops-table-toolbar">
              <div>
                <div className="ops-panel-title">{selectedRepo.name} settings</div>
                <p className="ops-subtle">Tune environment channel and retention behavior.</p>
              </div>
              <div className="ops-actions">
                <button className="btn btn-primary" onClick={updateRepo} disabled={actionLoading}>Save</button>
                <button className="btn btn-danger" onClick={removeRepo} disabled={actionLoading}>Delete</button>
              </div>
            </div>

            <div className="ops-form-grid">
              <select
                className="input"
                value={selectedRepo.provider}
                onChange={(e) =>
                  setRepos((prev) =>
                    prev.map((repo) => {
                      if (repo.id !== selectedRepo.id) return repo;
                      const nextProvider = e.target.value;
                      const prevDefault = providerDefaultSources[repo.provider] || '';
                      const nextDefault = providerDefaultSources[nextProvider] || '';
                      const shouldSwapDefault = !repo.source_url || repo.source_url === prevDefault;
                      return {
                        ...repo,
                        provider: nextProvider,
                        source_url: shouldSwapDefault ? nextDefault : repo.source_url,
                      };
                    }),
                  )
                }
              >
                {providers.map((provider) => <option key={provider.value} value={provider.value}>{provider.label}</option>)}
              </select>
              <select className="input" value={selectedRepo.os_family} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, os_family: e.target.value } : repo))}>
                {osFamilies.map((osFamily) => <option key={osFamily.value} value={osFamily.value}>{osFamily.label}</option>)}
              </select>
              <input className="input" value={selectedRepo.channel || ''} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, channel: e.target.value } : repo))} />
              <input className="input" value={selectedRepo.source_url || ''} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, source_url: e.target.value } : repo))} />
              <input className="input" type="number" min="5" value={selectedRepo.sync_interval_minutes || 360} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, sync_interval_minutes: e.target.value } : repo))} />
              <input className="input" type="number" min="1" value={selectedRepo.retention_days || 30} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, retention_days: e.target.value } : repo))} />
              <input className="input" type="number" min="1" value={selectedRepo.keep_versions || 2} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, keep_versions: e.target.value } : repo))} />
              <label className="toggle-option"><input type="checkbox" checked={Boolean(selectedRepo.enabled)} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, enabled: e.target.checked } : repo))} /> Enabled</label>
              <label className="toggle-option"><input type="checkbox" checked={Boolean(selectedRepo.metadata_only)} onChange={(e) => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, metadata_only: e.target.checked } : repo))} /> Metadata only</label>
              {selectedDefaultSource ? (
                <div className="ops-subtle" style={{ gridColumn: '1 / -1' }}>
                  Built-in source for {selectedRepo.provider}:
                  {' '}<code>{selectedDefaultSource}</code>
                  {' '}<button className="btn btn-sm" type="button" onClick={() => setRepos((prev) => prev.map((repo) => repo.id === selectedRepo.id ? { ...repo, source_url: selectedDefaultSource } : repo))}>
                    Apply built-in source
                  </button>
                </div>
              ) : (
                <div className="ops-subtle" style={{ gridColumn: '1 / -1' }}>
                  Custom Feed has no built-in URL. Provide your own source URL.
                </div>
              )}
              <label className="toggle-option" style={{ gridColumn: '1 / -1' }}>
                <input
                  type="checkbox"
                  checked={Boolean(isSatelliteRepo)}
                  onChange={(e) =>
                    patchSelectedRepo((repo) => ({
                      ...repo,
                      extra_config: {
                        ...(repo.extra_config || {}),
                        feed_family: e.target.checked ? 'satellite' : (repo.provider === 'redhat' ? 'redhat' : ''),
                        requires_source_url: e.target.checked,
                      },
                    }))
                  }
                />
                Satellite Mode (RHEL via Satellite/Katello)
              </label>
              {isSatelliteRepo && (
                <>
                  <input
                    className="input"
                    placeholder="Satellite Base URL (e.g. https://satellite.example.com)"
                    value={selectedRepo?.extra_config?.satellite_url || ''}
                    onChange={(e) =>
                      patchSelectedRepo((repo) => ({
                        ...repo,
                        extra_config: { ...(repo.extra_config || {}), satellite_url: e.target.value, feed_family: 'satellite' },
                      }))
                    }
                  />
                  <input
                    className="input"
                    placeholder="Satellite Organization ID or Name"
                    value={selectedRepo?.extra_config?.satellite_org || ''}
                    onChange={(e) =>
                      patchSelectedRepo((repo) => ({
                        ...repo,
                        extra_config: { ...(repo.extra_config || {}), satellite_org: e.target.value, feed_family: 'satellite' },
                      }))
                    }
                  />
                  <input
                    className="input"
                    placeholder="Satellite Environment ID or Name"
                    value={selectedRepo?.extra_config?.satellite_env || ''}
                    onChange={(e) =>
                      patchSelectedRepo((repo) => ({
                        ...repo,
                        extra_config: { ...(repo.extra_config || {}), satellite_env: e.target.value, feed_family: 'satellite' },
                      }))
                    }
                  />
                  <input
                    className="input"
                    placeholder={selectedRepo?.has_auth_token ? 'Token configured (enter new token to replace)' : 'Satellite API Token'}
                    value={selectedRepo?.auth_config?.token || ''}
                    onChange={(e) =>
                      patchSelectedRepo((repo) => ({
                        ...repo,
                        auth_config: { ...(repo.auth_config || {}), token: e.target.value },
                      }))
                    }
                  />
                  <div className="ops-subtle" style={{ gridColumn: '1 / -1' }}>
                    Satellite mode auto-builds errata API URL from base/org/env when Source URL is empty.
                  </div>
                </>
              )}
            </div>

            <div className="ops-actions" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={runSync} disabled={actionLoading}>Run Sync</button>
              <button className="btn btn-sm" onClick={runRetention} disabled={actionLoading}>Run Retention</button>
              <button className="btn btn-sm" onClick={previewRetention} disabled={actionLoading}>Preview Retention</button>
              <button className="btn btn-sm" onClick={refreshAll} disabled={actionLoading}>Refresh Details</button>
            </div>
          </div>

          <div className="ops-panel">
            <div className="ops-table-toolbar">
              <div>
                <div className="ops-panel-title">Latest sync runs</div>
                <p className="ops-subtle">Manual and scheduler run status with sync summaries.</p>
              </div>
            </div>
            {!runs.length ? (
              <div className="ops-empty">No sync runs yet.</div>
            ) : (
              <div className="ops-list">
                {runs.map((run) => (
                  <div key={run.id} className="ops-list-item">
                    <div className="ops-list-copy">
                      <strong>{run.status.toUpperCase()} · {run.trigger_type}</strong>
                      <span>{run.started_at ? new Date(run.started_at).toLocaleString() : '-'}</span>
                      <span>{run.error || `items=${run.summary?.items_seen ?? 0}, inserted=${run.summary?.inserted ?? 0}, updated=${run.summary?.updated ?? 0}`}</span>
                    </div>
                    <div className="ops-list-metrics">
                      <span className={`badge ${run.status === 'success' ? 'badge-success' : run.status === 'failed' ? 'badge-danger' : 'badge-info'}`}>{run.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {showDeleteDiagnostics && deleteDiagnostics && (
        <div className="modal-overlay">
          <div className="modal-card" style={{ maxWidth: 720 }}>
            <h3>Delete Diagnostics</h3>
            <p className="ops-subtle">Use this for support/debug escalation.</p>
            <table className="table">
              <tbody>
                <tr><td><strong>Repository</strong></td><td>{deleteDiagnostics.repo_name} (ID: {deleteDiagnostics.repo_id})</td></tr>
                <tr><td><strong>Status</strong></td><td>{deleteDiagnostics.status} {deleteDiagnostics.status_text}</td></tr>
                <tr><td><strong>Message</strong></td><td>{deleteDiagnostics.message || '-'}</td></tr>
                <tr><td><strong>Reason</strong></td><td>{deleteDiagnostics.reason || '-'}</td></tr>
                <tr><td><strong>Request ID</strong></td><td>{deleteDiagnostics.request_id || '-'}</td></tr>
                <tr><td><strong>Trace Token</strong></td><td>{deleteDiagnostics.trace_token || '-'}</td></tr>
                <tr><td><strong>Timestamp</strong></td><td>{deleteDiagnostics.timestamp}</td></tr>
              </tbody>
            </table>
            <div style={{ marginTop: 10 }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{JSON.stringify(deleteDiagnostics, null, 2)}</pre>
            </div>
            <div style={{ textAlign: 'right', marginTop: 12 }}>
              <button className="btn btn-sm" type="button" onClick={() => navigator.clipboard?.writeText(JSON.stringify(deleteDiagnostics, null, 2))}>Copy Diagnostics JSON</button>
              <button className="btn btn-primary" type="button" style={{ marginLeft: 8 }} onClick={() => setShowDeleteDiagnostics(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {selectedRepo && (
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Retention preview</div>
              <p className="ops-subtle">Dry-run for retention rules before actual cleanup.</p>
            </div>
          </div>
          {retentionPreviewTotal > 0 && (
            <div className="ops-chip-row" style={{ marginBottom: 12 }}>
              <span className="ops-chip">Would remove: {retentionPreviewTotal}</span>
              <span className="ops-chip">Showing: {retentionPreview.length}</span>
            </div>
          )}
          {!retentionPreview.length ? (
            <div className="ops-empty">Run "Preview Retention" to inspect candidates.</div>
          ) : (
            <table className="table ops-table">
              <thead>
                <tr>
                  <th>Package</th>
                  <th>Version</th>
                  <th>Arch</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {retentionPreview.map((item) => (
                  <tr key={item.id}>
                    <td><strong>{item.package_name}</strong></td>
                    <td>{item.package_version || '-'}</td>
                    <td>{item.architecture || '-'}</td>
                    <td>{item.reason || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {selectedRepo && (
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Catalog packages</div>
              <p className="ops-subtle">Current package index for the selected mirror channel.</p>
            </div>
            <div className="ops-actions">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <AppIcon name="search" size={16} />
                <input className="input" style={{ minWidth: 240 }} value={query} placeholder="Search package name" onChange={(e) => setQuery(e.target.value)} />
              </div>
            </div>
          </div>
          {!packages.length ? (
            <div className="ops-empty">No catalog packages found for this repository yet.</div>
          ) : (
            <table className="table ops-table">
              <thead>
                <tr>
                  <th>Package</th>
                  <th>Version</th>
                  <th>Fixed</th>
                  <th>Arch</th>
                  <th>Channel</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg) => (
                  <tr key={pkg.id}>
                    <td><strong>{pkg.package_name}</strong></td>
                    <td>{pkg.package_version}</td>
                    <td>{pkg.fixed_version || '-'}</td>
                    <td>{pkg.architecture || '-'}</td>
                    <td>{pkg.channel || '-'}</td>
                    <td>{pkg.last_seen_at ? new Date(pkg.last_seen_at).toLocaleString() : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {selectedRepo && (
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Installed vs available vs fixed</div>
              <p className="ops-subtle">Compare host inventory against the selected mirror catalog to validate rollout readiness.</p>
            </div>
            <div className="ops-actions">
              <select className="input" value={compareHostId} onChange={(e) => setCompareHostId(e.target.value)} style={{ minWidth: 240 }}>
                {hosts.map((host) => (
                  <option key={host.id} value={String(host.id)}>
                    {host.hostname} ({host.ip})
                  </option>
                ))}
              </select>
              <button className="btn btn-primary" onClick={runCompare} disabled={actionLoading || !compareHostId}>Run Compare</button>
            </div>
          </div>

          {compareError && <div className="ops-command-card" style={{ marginBottom: 12 }}>{compareError}</div>}

          {compareTotals && (
            <div className="ops-chip-row" style={{ marginBottom: 12 }}>
              <span className="ops-chip">Installed: {compareTotals.installed_count ?? 0}</span>
              <span className="ops-chip">Upgradable: {compareTotals.upgradable_count ?? 0}</span>
              <span className="ops-chip">Compared: {compareTotals.compared_count ?? 0}</span>
              <span className="ops-chip">Outdated: {compareTotals?.status?.outdated ?? 0}</span>
              <span className="ops-chip">Behind catalog: {compareTotals?.status?.behind_catalog ?? 0}</span>
            </div>
          )}

          {!compareRows.length ? (
            <div className="ops-empty">Run comparison to view package-level status.</div>
          ) : (
            <table className="table ops-table">
              <thead>
                <tr>
                  <th>Package</th>
                  <th>Installed</th>
                  <th>Upgradable</th>
                  <th>Catalog</th>
                  <th>Fixed</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.map((row, idx) => (
                  <tr key={`${row.package_name}-${idx}`}>
                    <td><strong>{row.package_name}</strong></td>
                    <td>{row.installed_version || '-'}</td>
                    <td>{row.upgradable_version || '-'}</td>
                    <td>{row.catalog_version || '-'}</td>
                    <td>{row.fixed_version || '-'}</td>
                    <td>
                      <span className={`badge ${
                        row.status === 'up_to_date' ? 'badge-success'
                          : row.status === 'outdated' || row.status === 'behind_catalog' ? 'badge-warning'
                            : 'badge-secondary'
                      }`}
                      >
                        {row.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
