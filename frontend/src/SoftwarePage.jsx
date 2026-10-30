import React, { useEffect, useMemo, useState } from 'react';
import { getUser } from './appRuntime';

const INITIAL_CATALOG_FORM = {
  name: '',
  package_name: '',
  description: '',
  supported_platforms: 'linux,windows',
  allowed_actions: 'install',
  default_execution_mode: 'immediate',
  is_enabled: true,
};

export default function SoftwarePage({ hosts, API, apiFetch }) {
  // Defensive check: ensure hosts is always an array
  const safeHosts = Array.isArray(hosts) ? hosts : [];
  
  const user = getUser() || {};
  const isPrivileged = ['admin', 'operator'].includes(user.role);
  const [view, setView] = useState('push');
  const [selectedHosts, setSelectedHosts] = useState([]);
  const [packages, setPackages] = useState('');
  const [action, setAction] = useState('install');
  const [executionMode, setExecutionMode] = useState('immediate');
  const [operatorNote, setOperatorNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [queueState, setQueueState] = useState({ loading: false, hostIp: '', items: [] });

  const [catalog, setCatalog] = useState([]);
  const [requests, setRequests] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [catalogForm, setCatalogForm] = useState(INITIAL_CATALOG_FORM);
  const [catalogMessage, setCatalogMessage] = useState('');
  const [kioskHostId, setKioskHostId] = useState('');
  const [kioskNote, setKioskNote] = useState('');
  const [kioskExecutionOverride, setKioskExecutionOverride] = useState('default');
  const [kioskMessage, setKioskMessage] = useState('');

  const toggleHost = (ip) => {
    setSelectedHosts((prev) => (
      prev.includes(ip) ? prev.filter((host) => host !== ip) : [...prev, ip]
    ));
  };

  const selectAll = () => setSelectedHosts(safeHosts.map((host) => host.ip));
  const selectNone = () => setSelectedHosts([]);

  const selectedSingleHost = selectedHosts.length === 1 ? selectedHosts[0] : '';
  const kioskHosts = useMemo(() => safeHosts.slice().sort((a, b) => (a.hostname || '').localeCompare(b.hostname || '')), [safeHosts]);

  const fetchCatalog = async () => {
    setCatalogLoading(true);
    try {
      const response = await apiFetch(`${API}/api/software-kiosk/catalog${isPrivileged ? '?include_disabled=true' : ''}`);
      const payload = await response.json();
      setCatalog(payload.items || []);
    } catch {
      setCatalog([]);
    }
    setCatalogLoading(false);
  };

  const fetchRequests = async () => {
    setRequestsLoading(true);
    try {
      const response = await apiFetch(`${API}/api/software-kiosk/requests`);
      const payload = await response.json();
      setRequests(payload.items || []);
    } catch {
      setRequests([]);
    }
    setRequestsLoading(false);
  };

  const fetchQueue = async (hostIp) => {
    if (!hostIp) {
      setQueueState({ loading: false, hostIp: '', items: [] });
      return;
    }
    setQueueState((prev) => ({ ...prev, loading: true, hostIp }));
    try {
      const response = await apiFetch(`${API}/api/agent/${hostIp}/software/queue`);
      const payload = await response.json();
      setQueueState({ loading: false, hostIp, items: payload.items || [] });
    } catch {
      setQueueState({ loading: false, hostIp, items: [] });
    }
  };

  useEffect(() => {
    fetchCatalog();
    fetchRequests();
  }, []);

  useEffect(() => {
    if (selectedSingleHost) {
      fetchQueue(selectedSingleHost);
    } else {
      setQueueState({ loading: false, hostIp: '', items: [] });
    }
  }, [selectedSingleHost]);

  const executeOperatorAction = async () => {
    if (!selectedHosts.length) {
      alert('Select hosts first.');
      return;
    }
    if (!packages.trim()) {
      alert('Enter package names.');
      return;
    }

    const pkgList = packages.split(',').map((item) => item.trim()).filter(Boolean);
    const modeLabel = executionMode === 'shutdown' ? 'queue for controlled shutdown' : 'run immediately';
    if (!window.confirm(`${action.toUpperCase()} ${pkgList.join(', ')} on ${selectedHosts.length} hosts and ${modeLabel}?`)) return;

    setLoading(true);
    setResults([]);

    for (const ip of selectedHosts) {
      try {
        const endpoint = executionMode === 'shutdown'
          ? `${API}/api/agent/${ip}/software/queue`
          : `${API}/api/agent/${ip}/software/manage`;
        const response = await apiFetch(endpoint, {
          method: 'POST',
          body: JSON.stringify({
            action,
            packages: pkgList,
            requested_by: user.username || 'operator',
            reason: operatorNote,
          }),
        });
        const payload = await response.json();
        setResults((prev) => [
          ...prev,
          {
            ip,
            status: response.ok ? 'success' : 'failed',
            message: payload.status || payload.message || payload.error || 'Completed',
          },
        ]);
      } catch (error) {
        setResults((prev) => [...prev, { ip, status: 'failed', message: error.message }]);
      }
    }

    setLoading(false);
    if (selectedSingleHost) {
      fetchQueue(selectedSingleHost);
    }
  };

  const runPowerAction = async (mode) => {
    if (!selectedSingleHost) return;
    const confirmText = mode === 'shutdown'
      ? `Run queued shutdown installs and power off ${selectedSingleHost}?`
      : `Run queued shutdown installs and reboot ${selectedSingleHost}?`;
    if (!window.confirm(confirmText)) return;
    try {
      const response = await apiFetch(`${API}/api/agent/${selectedSingleHost}/system/${mode}`, { method: 'POST' });
      const payload = await response.json();
      alert(payload.status || `${mode} scheduled`);
    } catch (error) {
      alert(error.message);
    }
  };

  const createCatalogItem = async () => {
    setCatalogMessage('');
    if (!catalogForm.name.trim() || !catalogForm.package_name.trim()) {
      setCatalogMessage('Name and package name are required.');
      return;
    }
    try {
      const response = await apiFetch(`${API}/api/software-kiosk/catalog`, {
        method: 'POST',
        body: JSON.stringify({
          name: catalogForm.name.trim(),
          package_name: catalogForm.package_name.trim(),
          description: catalogForm.description.trim(),
          supported_platforms: catalogForm.supported_platforms.split(',').map((v) => v.trim()).filter(Boolean),
          allowed_actions: catalogForm.allowed_actions.split(',').map((v) => v.trim()).filter(Boolean),
          default_execution_mode: catalogForm.default_execution_mode,
          is_enabled: catalogForm.is_enabled,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setCatalogMessage(payload.detail || payload.error || 'Failed to create catalog item.');
        return;
      }
      setCatalogMessage('Catalog item created.');
      setCatalogForm(INITIAL_CATALOG_FORM);
      fetchCatalog();
    } catch (error) {
      setCatalogMessage(error.message);
    }
  };

  const toggleCatalogItem = async (item) => {
    try {
      await apiFetch(`${API}/api/software-kiosk/catalog/${item.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          ...item,
          is_enabled: !item.is_enabled,
        }),
      });
      fetchCatalog();
    } catch (error) {
      setCatalogMessage(error.message);
    }
  };

  const submitKioskRequest = async (item, requestedAction) => {
    setKioskMessage('');
    if (!kioskHostId) {
      setKioskMessage('Choose a target host first.');
      return;
    }
    try {
      const response = await apiFetch(`${API}/api/software-kiosk/requests`, {
        method: 'POST',
        body: JSON.stringify({
          catalog_item_id: item.id,
          host_id: Number(kioskHostId),
          requested_action: requestedAction,
          execution_mode: kioskExecutionOverride === 'default' ? item.default_execution_mode : kioskExecutionOverride,
          note: kioskNote,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setKioskMessage(payload.detail || payload.error || 'Failed to submit request.');
        return;
      }
      setKioskMessage(`Request #${payload.id} submitted.`);
      setKioskNote('');
      fetchRequests();
    } catch (error) {
      setKioskMessage(error.message);
    }
  };

  const decideRequest = async (requestId, decision) => {
    try {
      const response = await apiFetch(`${API}/api/software-kiosk/requests/${requestId}/${decision}`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) {
        alert(payload.detail || payload.error || `Failed to ${decision} request.`);
        return;
      }
      fetchRequests();
    } catch (error) {
      alert(error.message);
    }
  };

  const summary = [
    { label: 'Hosts in scope', value: safeHosts.length, sub: `${selectedHosts.length} selected for operator push` },
    { label: 'Catalog items', value: catalog.length, sub: catalog.filter((item) => item.is_enabled).length + ' enabled for requests' },
    { label: 'Open requests', value: requests.filter((item) => item.status === 'submitted').length, sub: `${requests.length} total request records` },
    { label: 'Shutdown queue', value: queueState.items.length, sub: selectedSingleHost ? `for ${selectedSingleHost}` : 'pick one host to inspect queue' },
  ];

  return (
    <div className="ops-shell">
      <div className="card highlight-card">
        <h3>Software Distribution Workspace</h3>
        <p>
          Run operator-led package actions, maintain an approved self-service catalog, and queue installs for the next controlled shutdown or reboot.
          This gives Patch-SecOps Solution a real software distribution, kiosk, and shutdown-install workflow instead of just one-off package pushes.
        </p>
      </div>

      <div className="ops-summary-grid">
        {summary.map((card) => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value">{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="ops-panel">
        <div className="ops-pills">
          <button className={`ops-pill ${view === 'push' ? 'active' : ''}`} onClick={() => setView('push')}>Operator Push</button>
          <button className={`ops-pill ${view === 'kiosk' ? 'active' : ''}`} onClick={() => setView('kiosk')}>Approved Catalog</button>
        </div>
      </div>

      {view === 'push' && (
        <>
          <div className="card">
            <h3>1. Select Hosts ({selectedHosts.length})</h3>
            <div className="btn-group" style={{ marginBottom: 10 }}>
              <button className="btn btn-sm btn-primary" onClick={selectAll}>Select All</button>
              <button className="btn btn-sm" onClick={selectNone}>Deselect All</button>
            </div>
            <div style={{ maxHeight: 240, overflowY: 'auto', border: '1px solid #334155', padding: 10, borderRadius: 6 }}>
              {safeHosts.map((host) => (
                <label key={host.id} style={{ display: 'block', marginBottom: 4, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={selectedHosts.includes(host.ip)}
                    onChange={() => toggleHost(host.ip)}
                    style={{ marginRight: 8 }}
                  />
                  {host.hostname || host.name} ({host.ip}) <span className="text-muted">- {host.os || '--'}{host.site ? ` · ${host.site}` : ''}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>2. Configure Action</h3>
            <div className="form-row" style={{ marginBottom: 8 }}>
              <select className="input" value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 140 }}>
                <option value="install">Install</option>
                <option value="remove">Remove</option>
              </select>
              <select className="input" value={executionMode} onChange={(e) => setExecutionMode(e.target.value)} style={{ width: 220 }}>
                <option value="immediate">Execute immediately</option>
                <option value="shutdown">Queue for controlled shutdown</option>
              </select>
              <input
                className="input"
                placeholder="Package names (comma separated, e.g. git, curl, vim)"
                value={packages}
                onChange={(e) => setPackages(e.target.value)}
                style={{ flex: 1 }}
              />
            </div>
            <div className="form-row">
              <input
                className="input"
                placeholder="Reason / change ticket (optional)"
                value={operatorNote}
                onChange={(e) => setOperatorNote(e.target.value)}
                style={{ flex: 1 }}
              />
              <button className="btn btn-lg btn-success" onClick={executeOperatorAction} disabled={loading || !selectedHosts.length || !packages.trim()}>
                {loading ? 'Processing...' : executionMode === 'shutdown' ? 'Queue Action' : 'Execute'}
              </button>
            </div>
            <p className="text-muted" style={{ marginTop: 10 }}>
              Shutdown-queued actions are executed when Patch-SecOps Solution triggers a reboot or shutdown on that host.
            </p>
          </div>

          {selectedSingleHost && (
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div>
                  <h3>Controlled Shutdown Queue</h3>
                  <p className="text-muted" style={{ margin: 0 }}>{selectedSingleHost}</p>
                </div>
                <div className="btn-group">
                  <button className="btn btn-sm" onClick={() => fetchQueue(selectedSingleHost)}>{queueState.loading ? 'Refreshing...' : 'Refresh Queue'}</button>
                  <button className="btn btn-sm btn-warning" onClick={() => runPowerAction('reboot')}>Run Queue + Reboot</button>
                  <button className="btn btn-sm btn-danger" onClick={() => runPowerAction('shutdown')}>Run Queue + Shutdown</button>
                </div>
              </div>
              {queueState.items.length === 0 ? (
                <p className="text-muted">No shutdown installs are queued for this host.</p>
              ) : (
                <table className="table">
                  <thead><tr><th>Queued At</th><th>Action</th><th>Packages</th><th>Requested By</th><th>Reason</th></tr></thead>
                  <tbody>
                    {queueState.items.map((item) => (
                      <tr key={item.id}>
                        <td>{item.queued_at ? new Date(item.queued_at).toLocaleString() : '—'}</td>
                        <td>{item.action}</td>
                        <td>{Array.isArray(item.packages) ? item.packages.join(', ') : ''}</td>
                        <td>{item.requested_by || '—'}</td>
                        <td>{item.reason || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}

      {view === 'kiosk' && (
        <>
          <div className="card">
            <h3>Approved Catalog</h3>
            <div className="form-row" style={{ marginBottom: 10 }}>
              <select className="input" value={kioskHostId} onChange={(e) => setKioskHostId(e.target.value)} style={{ minWidth: 260 }}>
                <option value="">Choose target host</option>
                {kioskHosts.map((host) => (
                  <option key={host.id} value={host.id}>{host.hostname || host.name} ({host.ip})</option>
                ))}
              </select>
              <select className="input" value={kioskExecutionOverride} onChange={(e) => setKioskExecutionOverride(e.target.value)} style={{ width: 220 }}>
                <option value="default">Use catalog default</option>
                <option value="immediate">Force immediate install</option>
                <option value="shutdown">Force controlled shutdown install</option>
              </select>
            </div>
            <div className="form-row" style={{ marginBottom: 12 }}>
              <input
                className="input"
                placeholder="Request note (optional)"
                value={kioskNote}
                onChange={(e) => setKioskNote(e.target.value)}
              />
            </div>
            {kioskMessage && <div className="ops-empty" style={{ marginBottom: 12 }}>{kioskMessage}</div>}
            {catalogLoading ? (
              <p className="text-muted">Loading catalog...</p>
            ) : catalog.length === 0 ? (
              <p className="text-muted">No approved software catalog items are available yet.</p>
            ) : (
              <table className="table">
                <thead><tr><th>Name</th><th>Package</th><th>Platforms</th><th>Default Mode</th><th>Actions</th></tr></thead>
                <tbody>
                  {catalog.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.name}</strong>
                        <div className="text-muted">{item.description || 'No description'}</div>
                      </td>
                      <td><code>{item.package_name}</code></td>
                      <td>{(item.supported_platforms || []).join(', ') || 'Any'}</td>
                      <td>{item.default_execution_mode}</td>
                      <td style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {item.is_enabled && (item.allowed_actions || []).includes('install') && <button className="btn btn-sm btn-primary" onClick={() => submitKioskRequest(item, 'install')}>Request Install</button>}
                        {item.is_enabled && (item.allowed_actions || []).includes('remove') && <button className="btn btn-sm btn-warning" onClick={() => submitKioskRequest(item, 'remove')}>Request Remove</button>}
                        {!item.is_enabled && <span className="badge badge-warning">Disabled</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {isPrivileged && (
            <div className="card">
              <h3>Catalog Management</h3>
              <div className="form-row" style={{ marginBottom: 8 }}>
                <input className="input" placeholder="Display name" value={catalogForm.name} onChange={(e) => setCatalogForm((prev) => ({ ...prev, name: e.target.value }))} />
                <input className="input" placeholder="Package / winget / apt id" value={catalogForm.package_name} onChange={(e) => setCatalogForm((prev) => ({ ...prev, package_name: e.target.value }))} />
              </div>
              <div className="form-row" style={{ marginBottom: 8 }}>
                <input className="input" placeholder="Description" value={catalogForm.description} onChange={(e) => setCatalogForm((prev) => ({ ...prev, description: e.target.value }))} />
                <input className="input" placeholder="Platforms (comma separated)" value={catalogForm.supported_platforms} onChange={(e) => setCatalogForm((prev) => ({ ...prev, supported_platforms: e.target.value }))} />
              </div>
              <div className="form-row" style={{ marginBottom: 8 }}>
                <input className="input" placeholder="Allowed actions (install,remove)" value={catalogForm.allowed_actions} onChange={(e) => setCatalogForm((prev) => ({ ...prev, allowed_actions: e.target.value }))} />
                <select className="input" value={catalogForm.default_execution_mode} onChange={(e) => setCatalogForm((prev) => ({ ...prev, default_execution_mode: e.target.value }))} style={{ width: 220 }}>
                  <option value="immediate">Immediate by default</option>
                  <option value="shutdown">Controlled shutdown by default</option>
                </select>
                <label className="toggle-option" style={{ minWidth: 120 }}>
                  <input type="checkbox" checked={catalogForm.is_enabled} onChange={(e) => setCatalogForm((prev) => ({ ...prev, is_enabled: e.target.checked }))} />
                  Enabled
                </label>
                <button className="btn btn-success" onClick={createCatalogItem}>Add Item</button>
              </div>
              {catalogMessage && <div className="ops-empty">{catalogMessage}</div>}
              {catalog.length > 0 && (
                <table className="table" style={{ marginTop: 12 }}>
                  <thead><tr><th>Name</th><th>Package</th><th>Status</th><th>Operator Actions</th></tr></thead>
                  <tbody>
                    {catalog.map((item) => (
                      <tr key={item.id}>
                        <td>{item.name}</td>
                        <td><code>{item.package_name}</code></td>
                        <td>{item.is_enabled ? <span className="badge badge-success">Enabled</span> : <span className="badge badge-warning">Disabled</span>}</td>
                        <td><button className="btn btn-sm" onClick={() => toggleCatalogItem(item)}>{item.is_enabled ? 'Disable' : 'Enable'}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          <div className="card">
            <h3>Request Queue</h3>
            {requestsLoading ? (
              <p className="text-muted">Loading requests...</p>
            ) : requests.length === 0 ? (
              <p className="text-muted">No kiosk requests yet.</p>
            ) : (
              <table className="table">
                <thead><tr><th>ID</th><th>Requested</th><th>Target</th><th>Mode</th><th>Status</th><th>Requested By</th><th>Actions</th></tr></thead>
                <tbody>
                  {requests.map((item) => (
                    <tr key={item.id}>
                      <td>#{item.id}</td>
                      <td>
                        <strong>{item.catalog_item?.name}</strong>
                        <div className="text-muted">{item.requested_action} · {item.note || 'No note'}</div>
                      </td>
                      <td>{item.host?.hostname || 'Unknown'}<div className="text-muted">{item.host?.ip || ''}</div></td>
                      <td>{item.execution_mode}</td>
                      <td>
                        <span className={`badge badge-${item.status === 'submitted' ? 'warning' : item.status === 'rejected' || item.status === 'failed' ? 'danger' : 'success'}`}>{item.status}</span>
                        {item.status_message && <div className="text-muted">{item.status_message}</div>}
                      </td>
                      <td>{item.requested_by?.username || '—'}</td>
                      <td style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {isPrivileged && item.status === 'submitted' && <button className="btn btn-sm btn-success" onClick={() => decideRequest(item.id, 'approve')}>Approve</button>}
                        {isPrivileged && item.status === 'submitted' && <button className="btn btn-sm btn-danger" onClick={() => decideRequest(item.id, 'reject')}>Reject</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {results.length > 0 && (
        <div className="card">
          <h3>Operator Results</h3>
          <table className="table">
            <thead><tr><th>Host</th><th>Status</th><th>Details</th></tr></thead>
            <tbody>
              {results.map((result, index) => (
                <tr key={`${result.ip}-${index}`}>
                  <td>{result.ip}</td>
                  <td><span className={`badge badge-${result.status === 'success' ? 'success' : 'danger'}`}>{result.status}</span></td>
                  <td>{result.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
