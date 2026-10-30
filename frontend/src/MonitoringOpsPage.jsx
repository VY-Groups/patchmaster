import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

function GrafanaBadge({ size = 18 }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="#F97316" opacity="0.16" />
      <circle cx="12" cy="12" r="4.5" fill="#F97316" />
      <circle cx="8" cy="8" r="2.2" fill="#FBBF24" />
      <circle cx="15.8" cy="7.2" r="1.8" fill="#FB923C" />
      <circle cx="17" cy="14.8" r="2" fill="#EA580C" />
    </svg>
  );
}

function PromBadge({ size = 18 }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="#E6522C" opacity="0.14" />
      <path d="M8 16.5h8M9.5 7.8h5l1.8 3.3-3.4 5.4H10.7L7.3 11l2.2-3.2Z" fill="#E6522C" />
      <circle cx="12" cy="11.8" r="2.1" fill="#fff" opacity="0.95" />
    </svg>
  );
}

export default function MonitoringOpsPage({ licenseInfo, hosts = [], API, apiFetch, hasRole, getToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [enforcing, setEnforcing] = useState(false);
  const [booting, setBooting] = useState(false);
  const [actionMsg, setActionMsg] = useState('');
  const [metricsStatus, setMetricsStatus] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const masterIp = window.location.hostname;

  const normalizeServices = useCallback((svcObj = {}) => {
    const blocked = ['zabbix', 'zabbix-server', 'zabbix_proxy', 'zabbix-agent', 'zabbix_agentd'];
    const normalized = {};
    const normKey = (value) => {
      const key = String(value || '').toLowerCase().replace(/\.service$/, '').replace(/_/g, '-');
      if (key.startsWith('grafana')) return 'grafana';
      if (key.startsWith('prometheus')) return 'prometheus';
      return key;
    };
    for (const [rawKey, val] of Object.entries(svcObj)) {
      const key = normKey(rawKey);
      if (blocked.includes(key)) continue;
      const merged = normalized[key] || {};
      normalized[key] = {
        name: key === 'grafana' ? 'Grafana' : key === 'prometheus' ? 'Prometheus' : (val.name || merged.name || rawKey),
        installed: Boolean(val.installed) || Boolean(val.running) || Boolean(merged.installed),
        running: Boolean(val.running),
        port: val.port || merged.port,
      };
    }
    return normalized;
  }, []);

  const licenseHasMonitoring = Array.isArray(licenseInfo?.features) && licenseInfo.features.includes('monitoring') && !licenseInfo?.expired;

  const fetchStatus = useCallback(() => {
    setLoading(true);
    apiFetch(`${API}/api/monitoring/status`)
      .then(r => r.json())
      .then(d => setData({ ...d, services: normalizeServices(d.services || {}) }))
      .finally(() => setLoading(false));
    apiFetch(`${API}/api/monitoring/health`)
      .then(r => r.json())
      .then(d => setMetricsStatus(normalizeServices(d.services || {})))
      .catch(() => setMetricsStatus(null));
  }, [API, apiFetch, normalizeServices]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleEnforce = () => {
    setEnforcing(true);
    setActionMsg('');
    apiFetch(`${API}/api/monitoring/enforce`, { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        setActionMsg(d.action === 'started' ? 'Monitoring services started.' : 'Monitoring services stopped.');
        fetchStatus();
      })
      .catch(() => setActionMsg('Monitoring enforcement failed.'))
      .finally(() => setEnforcing(false));
  };

  const handleBootstrap = () => {
    setBooting(true);
    setActionMsg('Applying monitoring configuration...');
    apiFetch(`${API}/api/monitoring/bootstrap`, { method: 'POST' })
      .then(r => r.json())
      .then(() => {
        setActionMsg('Monitoring stack refreshed.');
        fetchStatus();
      })
      .catch(() => setActionMsg('Monitoring bootstrap failed.'))
      .finally(() => setBooting(false));
  };

  const buildMonitoringUrl = useCallback((service, servicePath = '', query = {}) => {
    const cleanPath = servicePath ? `/${String(servicePath).replace(/^\/+/, '')}` : '/';
    const useUiOrigin = !['localhost', '127.0.0.1'].includes(window.location.hostname);
    const base = useUiOrigin ? `/api/monitoring/embed/${service}${cleanPath}` : `${API}/api/monitoring/embed/${service}${cleanPath}`;
    const url = new URL(base, window.location.origin);
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value);
    });
    return url.toString();
  }, [API]);

  const serviceCatalog = useMemo(() => ({
    prometheus: {
      key: 'prometheus',
      name: 'Prometheus',
      description: 'Metrics collection and alerting',
      defaultPort: 9090,
      icon: <PromBadge size={34} />,
      openUrl: buildMonitoringUrl('prometheus'),
      embedUrl: buildMonitoringUrl('prometheus'),
      frameTitle: 'Prometheus',
    },
    grafana: {
      key: 'grafana',
      name: 'Grafana',
      description: 'Dashboards and visualization',
      defaultPort: 3001,
      icon: <GrafanaBadge size={34} />,
      openUrl: buildMonitoringUrl('grafana'),
      embedUrl: buildMonitoringUrl('grafana', '', { kiosk: 'tv' }),
      frameTitle: 'Grafana Dashboards',
    },
  }), [buildMonitoringUrl]);

  const licensed = (data?.licensed ?? false) || licenseHasMonitoring;
  const services = data?.services || {};
  const tierLabel = data?.tier_label || licenseInfo?.tier_label || 'Unknown';
  const monitoringServices = ['prometheus', 'grafana'].map((serviceKey) => {
    const status = { ...(services[serviceKey] || {}), ...(metricsStatus?.[serviceKey] || {}) };
    const meta = serviceCatalog[serviceKey];
    return {
      ...meta,
      installed: Boolean(status.installed),
      running: Boolean(status.running),
      port: status.port || meta.defaultPort,
    };
  });
  const servicesByKey = monitoringServices.reduce((acc, service) => ({ ...acc, [service.key]: service }), {});
  const metricsServices = metricsStatus || {};
  const serviceStateCards = monitoringServices.map(service => ({
    label: service.name,
    value: service.running ? 'RUNNING' : service.installed ? 'STOPPED' : 'OFFLINE',
    sub: `Port ${service.port} - ${service.description}`,
    color: service.running ? '#16a34a' : service.installed ? '#d97706' : '#dc2626',
    bg: service.running ? 'rgba(34,197,94,0.12)' : service.installed ? 'rgba(245,158,11,0.14)' : 'rgba(239,68,68,0.12)',
    icon: service.key,
  }));

  const currentService = activeTab === 'overview' ? null : servicesByKey[activeTab];
  const hostDashboardLinks = useMemo(() => {
    const grouped = {};
    (hosts || []).forEach(h => {
      if (!h?.ip) return;
      if (!grouped[h.ip]) grouped[h.ip] = [];
      grouped[h.ip].push(h);
    });
    const links = [];
    Object.entries(grouped).forEach(([ip, list]) => {
      const win = list.find(h => String(h.os || '').toLowerCase().includes('win'));
      const linux = list.filter(h => !String(h.os || '').toLowerCase().includes('win'));
      if (win) {
        // Windows agent metrics run on the same port as Linux (9100) — 18080 is the API port
        links.push({
          id: `win-${win.id || ip}`,
          host: win,
          target: `${ip}:9100`,
          kind: 'windows',
        });
      }
      if (linux.length) {
        // Linux agents always run on 8080 — only one metrics target per IP for Linux
        links.push({
          id: `lin-${linux[0].id || ip}`,
          host: linux[0],
          target: `${ip}:9100`,
          kind: 'linux',
        });
      }
      if (!win && !linux.length && list[0]) {
        links.push({
          id: `unk-${list[0].id || ip}`,
          host: list[0],
          target: `${ip}:9100`,
          kind: 'unknown',
        });
      }
    });
    return links;
  }, [hosts]);

  const heroTone = licensed
    ? {
        title: 'Monitoring stack available',
        description: `${tierLabel} tier enables embedded dashboards and service-level health visibility for Prometheus and Grafana.`,
        bg: 'linear-gradient(145deg, #ecfdf3, #f8fffb)',
        border: '#86efac',
        color: '#166534',
      }
    : {
        title: 'Monitoring is not licensed',
        description: `A higher license tier is required to run and embed the monitoring stack. Current tier: ${tierLabel}.`,
        bg: 'linear-gradient(145deg, #fef2f2, #fff7f7)',
        border: '#fca5a5',
        color: '#b91c1c',
      };

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: heroTone.border, background: heroTone.bg }}>
          <div className="ops-kicker">Monitoring operations</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">License state</span>
              <span className="ops-emphasis-value" style={{ color: heroTone.color }}>{licensed ? 'ON' : 'OFF'}</span>
              <span className="ops-emphasis-meta">{licensed ? `${tierLabel} tier` : 'Feature unavailable on current tier'}</span>
            </div>
            <div className="ops-hero-copy">
              <h3>{heroTone.title}</h3>
              <p>{heroTone.description}</p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">Prometheus metrics on `/metrics`</span>
            <span className="ops-chip">Grafana embed support</span>
            <span className="ops-chip">Prometheus port 9090</span>
            <span className="ops-chip">Grafana port 3001</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <div className="ops-table-toolbar" style={{ marginBottom: 12 }}>
            <div>
              <span className="ops-side-label">Admin actions</span>
              <div className="ops-side-metric">{licensed ? 'Ready' : 'Blocked'}</div>
            </div>
            <button className="btn btn-sm" onClick={fetchStatus}>Refresh</button>
          </div>
          <div className="ops-actions" style={{ width: '100%' }}>
            {licensed && hasRole('admin') && (
              <>
                <button className="btn btn-primary" onClick={handleEnforce} disabled={enforcing || booting}>{enforcing ? 'Working...' : 'Start All'}</button>
                <button className="btn btn-secondary" onClick={handleBootstrap} disabled={booting || enforcing}>{booting ? 'Applying...' : 'Repair Embed Access'}</button>
              </>
            )}
          </div>
          {actionMsg && <p className="ops-subtle" style={{ marginTop: 12 }}>{actionMsg}</p>}
        </div>
      </div>

      <div className="ops-summary-grid">
        {serviceStateCards.map(card => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                {card.icon === 'grafana' ? <GrafanaBadge size={18} /> : <PromBadge size={18} />}
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value" style={{ fontSize: 24 }}>{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
        <div className="ops-summary-card">
          <div className="ops-summary-head">
            <span className="ops-summary-icon" style={{ color: '#2563eb', background: 'rgba(37,99,235,0.12)' }}>PM</span>
            <span className="ops-summary-label">Patch-SecOps Solution Endpoint</span>
          </div>
          <div className="ops-summary-value" style={{ fontSize: 24 }}>/metrics</div>
          <div className="ops-summary-sub">{masterIp}:8000 scrape target for Prometheus</div>
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Workspace</div>
            <p className="ops-subtle">Switch between service overview and embedded live views without leaving Patch-SecOps Solution.</p>
          </div>
        </div>
        <div className="ops-pills">
          {[
            { key: 'overview', label: 'Overview', enabled: true },
            { key: 'grafana', label: 'Grafana', enabled: Boolean(servicesByKey.grafana?.running) },
            { key: 'prometheus', label: 'Prometheus', enabled: Boolean(servicesByKey.prometheus?.running) },
          ].map(tab => (
            <button
              key={tab.key}
              className={`ops-pill ${activeTab === tab.key ? 'active' : ''}`}
              onClick={() => tab.enabled && setActiveTab(tab.key)}
              disabled={!tab.enabled}
              style={!tab.enabled ? { opacity: 0.55, cursor: 'not-allowed' } : undefined}
            >
              {tab.label}{!tab.enabled && tab.key !== 'overview' ? ' (offline)' : ''}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'overview' && (
        <>
          <div className="grid-2">
            <div className="ops-panel">
              <div className="ops-table-toolbar">
                <div>
                  <div className="ops-panel-title">Service status</div>
                  <p className="ops-subtle">Installed state, runtime status, and direct entry points for both monitoring services.</p>
                </div>
              </div>
              {loading ? (
                <div className="ops-empty">Checking monitoring services...</div>
              ) : (
                <div className="ops-list">
                  {monitoringServices.map(service => (
                    <div key={service.key} className="ops-list-item">
                      <div className="ops-list-copy">
                        <strong>{service.name}</strong>
                        <span>{service.description} - port {service.port}</span>
                      </div>
                      <div className="ops-list-metrics">
                        <span className={`badge badge-${service.running ? 'success' : service.installed ? 'warning' : 'danger'}`}>
                          {service.running ? 'RUNNING' : service.installed ? 'STOPPED' : 'NOT INSTALLED'}
                        </span>
                        {service.running && <a href={service.openUrl} target="_blank" rel="noreferrer" className="btn btn-sm btn-primary">Open</a>}
                        {service.running && <button className="btn btn-sm" onClick={() => setActiveTab(service.key)}>Embed View</button>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="ops-panel">
              <div className="ops-table-toolbar">
                <div>
                  <div className="ops-panel-title">Metrics scrape config</div>
                  <p className="ops-subtle">Patch-SecOps Solution exposes Prometheus-format metrics directly from the application backend.</p>
                </div>
              </div>
              <pre className="code-block">{`# prometheus.yml scrape config
- job_name: 'patchmaster'
  metrics_path: '/metrics'
  static_configs:
    - targets: ['${masterIp}:8000']`}</pre>
              <div className="ops-list" style={{ marginTop: 16 }}>
                {['prometheus', 'grafana'].map(key => {
                  const status = metricsServices[key] || servicesByKey[key];
                  if (!status) return null;
                  return (
                    <div key={key} className="ops-list-item">
                      <div className="ops-list-copy">
                        <strong>{key === 'grafana' ? 'Grafana' : 'Prometheus'}</strong>
                        <span>Health endpoint status from the monitoring backend</span>
                      </div>
                      <div className="ops-list-metrics">
                        <span className={`badge badge-${status.running ? 'success' : status.installed ? 'warning' : 'danger'}`}>
                          {status.running ? 'UP' : status.installed ? 'STOPPED' : 'OFFLINE'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="ops-panel">
            <div className="ops-table-toolbar">
              <div>
                <div className="ops-panel-title">Monitoring by license tier</div>
                <p className="ops-subtle">This helps explain to end users why monitoring features are available or blocked in their current subscription.</p>
              </div>
            </div>
            <div className="table-wrap">
              <table className="table ops-table">
                <thead>
                  <tr><th>Feature</th><th>Basic</th><th>Standard</th><th>DevOps</th><th>Enterprise</th></tr>
                </thead>
                <tbody>
                  <tr><td>Prometheus</td><td>No</td><td>Yes</td><td>Yes</td><td>Yes</td></tr>
                  <tr><td>Grafana</td><td>No</td><td>Yes</td><td>Yes</td><td>Yes</td></tr>
                  <tr><td>Embedded dashboards</td><td>No</td><td>Yes</td><td>Yes</td><td>Yes</td></tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="ops-panel">
            <div className="ops-table-toolbar">
              <div>
                <div className="ops-panel-title">Per-Host Dashboards (Auto)</div>
                <p className="ops-subtle">Every discovered host gets a direct Host Details link automatically. Linux and Windows targets are mapped separately when sharing the same IP.</p>
              </div>
            </div>
            {hostDashboardLinks.length === 0 ? (
              <div className="ops-empty">No hosts discovered yet.</div>
            ) : (
              <div className="ops-list">
                {hostDashboardLinks.map(item => (
                  <div key={item.id} className="ops-list-item">
                    <div className="ops-list-copy">
                      <strong>{item.host.hostname || item.host.name || item.host.ip}</strong>
                      <span>{item.kind.toUpperCase()} · {item.target}</span>
                    </div>
                    <div className="ops-list-metrics">
                      <a
                        href={buildMonitoringUrl('grafana', 'd/pm-host-details', { 'var-instance': item.target })}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-sm btn-primary"
                      >
                        Open Host Dashboard
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {activeTab !== 'overview' && (
        <div className="ops-panel" style={{ padding: 0, overflow: 'hidden' }}>
          {!currentService?.running ? (
            <div className="ops-empty" style={{ margin: 22 }}>This monitoring service is not currently running.</div>
          ) : (
            <>
              <div style={{ padding: '14px 18px', background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#fff' }}>
                  {activeTab === 'grafana' ? <GrafanaBadge size={22} /> : <PromBadge size={22} />}
                  <strong>{currentService.name}</strong>
                  <span className="badge badge-success">LIVE</span>
                </div>
                <a href={currentService.openUrl} target="_blank" rel="noreferrer" className="btn btn-sm btn-primary">Open Full Screen</a>
              </div>
              <iframe
                src={currentService.embedUrl}
                title={currentService.frameTitle}
                style={{ width: '100%', height: '75vh', border: 'none', background: '#fff' }}
                loading="lazy"
                referrerPolicy="same-origin"
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}

{/* placeholder */}
