import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

const numberFmt = new Intl.NumberFormat();

function formatSize(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount)) return '0 MB';
  return `${amount >= 100 ? amount.toFixed(0) : amount.toFixed(1)} MB`;
}

function extensionFor(name) {
  const lower = String(name || '').toLowerCase();
  if (lower.endsWith('.tar.gz')) return 'tar.gz';
  const parts = lower.split('.');
  return parts.length > 1 ? parts.pop() : 'file';
}

export default function LocalRepoOpsPage({ API, apiFetch, AppIcon }) {
  const [packages, setPackages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [query, setQuery] = useState('');

  const fetchPackages = useCallback(() => {
    setLoading(true);
    apiFetch(`${API}/api/packages/local/`)
      .then((response) => response.json())
      .then((payload) => setPackages(Array.isArray(payload?.packages) ? payload.packages : []))
      .catch(() => setMessage('Unable to load repository packages right now.'))
      .finally(() => setLoading(false));
  }, [API, apiFetch]);

  useEffect(() => {
    fetchPackages();
  }, [fetchPackages]);

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    setLoading(true);
    setMessage('');
    try {
      const response = await apiFetch(`${API}/api/packages/local/upload`, {
        method: 'POST',
        body: formData,
      });
      if (response.ok) {
        setMessage('Package uploaded successfully.');
        fetchPackages();
      } else {
        const payload = await response.json().catch(() => ({}));
        setMessage(payload.detail || 'Upload failed.');
      }
    } catch (error) {
      setMessage(`Error: ${error.message}`);
    } finally {
      event.target.value = '';
      setLoading(false);
    }
  };

  const deletePackage = async (name) => {
    if (!window.confirm(`Delete ${name}?`)) return;
    setMessage('');
    try {
      const response = await apiFetch(`${API}/api/packages/local/${name}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Delete failed.');
      setMessage('Package deleted successfully.');
      fetchPackages();
    } catch (error) {
      setMessage(`Error: ${error.message}`);
    }
  };

  const filteredPackages = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = [...packages].sort((a, b) => (b.created || 0) - (a.created || 0));
    if (!needle) return sorted;
    return sorted.filter((pkg) => String(pkg?.name || '').toLowerCase().includes(needle));
  }, [packages, query]);

  const stats = useMemo(() => {
    const totalStorage = packages.reduce((sum, item) => sum + Number(item?.size_mb || 0), 0);
    const latest = [...packages].sort((a, b) => (b.created || 0) - (a.created || 0))[0];
    const windowsReady = packages.filter((pkg) => ['msi', 'exe'].includes(extensionFor(pkg?.name))).length;
    const linuxReady = packages.filter((pkg) => ['deb', 'rpm'].includes(extensionFor(pkg?.name))).length;
    return { totalStorage, latest, windowsReady, linuxReady };
  }, [packages]);

  const typeBreakdown = useMemo(() => {
    const counts = new Map();
    packages.forEach((pkg) => {
      const ext = extensionFor(pkg?.name).toUpperCase();
      counts.set(ext, (counts.get(ext) || 0) + 1);
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [packages]);

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#86efac', background: 'linear-gradient(145deg, #ecfdf3, #f7fffb)' }}>
          <div className="ops-kicker">Local repository</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Air-gapped stock</span>
              <span className="ops-emphasis-value" style={{ color: '#166534' }}>{numberFmt.format(packages.length)}</span>
              <span className="ops-emphasis-meta">{formatSize(stats.totalStorage)} stored on the Patch-SecOps Solution master node.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Stage approved packages once, then distribute them to disconnected systems with confidence.</h3>
              <p>
                Local Repository is now a proper package operations workspace for air-gapped environments. Upload approved artifacts, monitor repository inventory, and keep operators aligned on the exact workflow for pushing packages from the master node to endpoints.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">Supports .deb and .rpm</span>
            <span className="ops-chip">Windows .msi and .exe</span>
            <span className="ops-chip">Secure host push workflow</span>
            <span className="ops-chip">Air-gapped ready</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Repository focus</span>
          <div className="ops-side-metric">Curated</div>
          <p className="ops-side-note">
            Treat this like a controlled distribution shelf: upload validated packages, review what is available, and only promote the artifacts your operators should see when pushing from the master repository.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>{numberFmt.format(stats.linuxReady)}</strong>
              <span>Linux-ready packages</span>
            </div>
            <div className="ops-inline-card">
              <strong>{numberFmt.format(stats.windowsReady)}</strong>
              <span>Windows-ready packages</span>
            </div>
            <div className="ops-inline-card">
              <strong>{stats.latest ? 'Fresh' : 'Empty'}</strong>
              <span>{stats.latest ? `latest: ${stats.latest.name}` : 'upload to seed the repo'}</span>
            </div>
            <div className="ops-inline-card">
              <strong>{formatSize(stats.totalStorage)}</strong>
              <span>repository capacity in use</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {[
          { label: 'Stored packages', value: numberFmt.format(packages.length), sub: 'files available for host push', icon: 'archive', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
          { label: 'Repository size', value: formatSize(stats.totalStorage), sub: 'current package storage footprint', icon: 'database', color: '#0f766e', bg: 'rgba(16,185,129,0.12)' },
          { label: 'Latest upload', value: stats.latest ? extensionFor(stats.latest.name).toUpperCase() : 'None', sub: stats.latest ? stats.latest.name : 'repository not seeded yet', icon: 'package', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
          { label: 'Distribution mode', value: 'Air-gapped', sub: 'push packages from the master node to agents', icon: 'cloud-off', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
        ].map((card) => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value" style={{ fontSize: typeof card.value === 'string' && card.value.length > 12 ? 22 : 28 }}>{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Repository inventory</div>
            <p className="ops-subtle">Search, upload, and remove repository packages without leaving the page.</p>
          </div>
          <div className="ops-actions">
            <button className="btn btn-sm" onClick={fetchPackages}>Refresh</button>
            <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
              Upload package
              <input type="file" style={{ display: 'none' }} accept=".deb,.rpm,.msi,.exe,.zip,.tar.gz,.tgz" onChange={handleUpload} />
            </label>
          </div>
        </div>

        <div className="ops-form-grid" style={{ marginBottom: 14 }}>
          <input className="input" placeholder="Search repository by filename" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>

        {message && (
          <div
            className="ops-command-card"
            style={{
              marginBottom: 16,
              borderColor: message.toLowerCase().includes('error') || message.toLowerCase().includes('failed') ? '#fecaca' : '#86efac',
              background: message.toLowerCase().includes('error') || message.toLowerCase().includes('failed')
                ? 'linear-gradient(145deg, #fff7ed, #fffdf8)'
                : 'linear-gradient(145deg, #ecfdf3, #f8fffb)',
            }}
          >
            <div style={{ color: message.toLowerCase().includes('error') || message.toLowerCase().includes('failed') ? '#b45309' : '#166534', fontWeight: 700 }}>{message}</div>
          </div>
        )}

        {loading && !packages.length ? (
          <div className="ops-empty">Loading repository packages...</div>
        ) : !filteredPackages.length ? (
          <div className="ops-empty">No packages match the current filter.</div>
        ) : (
          <table className="table ops-table">
            <thead>
              <tr>
                <th>Package</th>
                <th>Type</th>
                <th>Size</th>
                <th>Uploaded</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredPackages.map((pkg) => {
                const ext = extensionFor(pkg.name).toUpperCase();
                return (
                  <tr key={pkg.name}>
                    <td>
                      <strong>{pkg.name}</strong>
                      <span className="ops-table-meta">Available for Push from Master Repo actions.</span>
                    </td>
                    <td><span className="badge badge-info">{ext}</span></td>
                    <td>{formatSize(pkg.size_mb)}</td>
                    <td>{pkg.created ? new Date(pkg.created * 1000).toLocaleString() : 'Unknown'}</td>
                    <td>
                      <button className="btn btn-sm btn-danger" onClick={() => deletePackage(pkg.name)}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Recommended workflow</div>
              <p className="ops-subtle">A simple package governance loop for operators managing disconnected networks.</p>
            </div>
          </div>
          <div className="ops-list">
            {[
              'Upload a vetted package from your packaging or release team.',
              'Review the inventory list and confirm the filename matches your rollout plan.',
              'Open the target host and choose Push from Master Repo.',
              'Track the install job and keep the repository clean by removing superseded builds.',
            ].map((step) => (
              <div key={step} className="ops-list-item">
                <div className="ops-list-copy">
                  <strong>{step}</strong>
                  <span>Designed for controlled environments where endpoints do not have direct internet access.</span>
                </div>
                <div className="ops-list-metrics">
                  <span className="badge badge-success">Best practice</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Repository mix</div>
              <p className="ops-subtle">See which package types are dominating the air-gapped inventory.</p>
            </div>
          </div>
          {!typeBreakdown.length ? (
            <div className="ops-empty">Upload packages to build a repository mix view.</div>
          ) : (
            <div className="ops-list">
              {typeBreakdown.map(([ext, count]) => (
                <div key={ext} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{ext}</strong>
                    <span>{count} package{count === 1 ? '' : 's'} ready for controlled distribution.</span>
                  </div>
                  <div className="ops-list-metrics">
                    <span className="badge badge-info">{count}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
