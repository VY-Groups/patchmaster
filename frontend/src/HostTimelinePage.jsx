import React, { useCallback, useEffect, useMemo, useState } from 'react';

export default function HostTimelinePage({ hosts, API, apiFetch, CodeIcon }) {
  const [selectedHostId, setSelectedHostId] = useState('');
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState('all');

  const hostList = Array.isArray(hosts) ? hosts : [];
  const selectedHost = hostList.find(h => String(h.id) === String(selectedHostId));

  useEffect(() => {
    if (!selectedHostId && hostList.length) {
      setSelectedHostId(String(hostList[0].id));
    }
  }, [hostList, selectedHostId]);

  const typeMeta = {
    all: { label: 'All Events', code: 'AL', tone: '#1d4ed8', bg: 'rgba(37,99,235,0.12)' },
    patch: { label: 'Patch', code: 'PT', tone: '#15803d', bg: 'rgba(34,197,94,0.14)' },
    snapshot: { label: 'Snapshot', code: 'SN', tone: '#06b6d4', bg: 'rgba(139,92,246,0.14)' },
    cve: { label: 'CVE', code: 'CV', tone: '#dc2626', bg: 'rgba(239,68,68,0.14)' },
    reboot: { label: 'Reboot', code: 'RB', tone: '#b45309', bg: 'rgba(245,158,11,0.16)' },
    agent_update: { label: 'Agent Update', code: 'AU', tone: '#0369a1', bg: 'rgba(14,165,233,0.14)' },
    login: { label: 'Login', code: 'LG', tone: '#475569', bg: 'rgba(148,163,184,0.16)' },
  };
  const severityColor = { success: '#10b981', info: '#3b82f6', warning: '#f59e0b', danger: '#ef4444' };

  const fetchTimeline = useCallback(async () => {
    if (!selectedHostId) {
      setEvents([]);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (typeFilter !== 'all') params.set('event_type', typeFilter);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const res = await apiFetch(`${API}/api/hosts/${selectedHostId}/timeline${suffix}`);
      const data = await res.json();
      setEvents(Array.isArray(data) ? data : []);
    } catch {
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, [selectedHostId, typeFilter]);

  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);

  return (
    <div>
      <div className="card highlight-card">
        <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 12 }}>
          <CodeIcon code="TL" size={20} />
          Host Timeline
        </h2>
        <p style={{ marginTop: 8, opacity: 0.8 }}>
          Full event history per host - patches, CVEs, reboots, snapshots, and agent updates.
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <h3>Filters</h3>
          <button className="btn btn-sm" onClick={fetchTimeline} disabled={loading || !selectedHostId}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Host</label>
            <select className="input" value={selectedHostId} onChange={e => setSelectedHostId(e.target.value)}>
              <option value="">-- Select a host --</option>
              {hostList.map(h => (
                <option key={h.id} value={h.id}>{h.hostname || h.name} ({h.ip})</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Event Type</label>
            <select className="input" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
              {Object.entries(typeMeta).map(([value, meta]) => (
                <option key={value} value={value}>{meta.label}</option>
              ))}
            </select>
          </div>
        </div>
        {selectedHost && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
            <span className={`badge ${selectedHost.is_online ? 'badge-success' : 'badge-danger'}`}>{selectedHost.is_online ? 'Online' : 'Offline'}</span>
            <span className="badge badge-info">{selectedHost.os || 'Unknown OS'}</span>
            {selectedHost.agent_version && <span className="badge badge-info">Agent {selectedHost.agent_version}</span>}
            <span className="badge badge-info">{selectedHost.ip}</span>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Event Stream</h3>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{events.length} item{events.length === 1 ? '' : 's'}</span>
        </div>
        {!selectedHostId && <p style={{ color: 'var(--text-secondary)' }}>Select a host to view timeline activity.</p>}
        {selectedHostId && !loading && !events.length && <p style={{ color: 'var(--text-secondary)' }}>No events found for this host and filter.</p>}
        <div style={{ display: 'grid', gap: 12 }}>
          {events.map(event => {
            const meta = typeMeta[event.event_type] || { label: event.event_type || 'Event', code: 'EV', tone: '#475569', bg: 'rgba(148,163,184,0.16)' };
            return (
              <div
                key={event.id}
                style={{
                  border: `1px solid ${severityColor[event.severity] || '#cbd5e1'}`,
                  borderLeftWidth: 4,
                  borderRadius: 12,
                  padding: 14,
                  background: 'var(--card-bg)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <CodeIcon code={meta.code} tone={meta.tone} bg={meta.bg} size={18} />
                    <div>
                      <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{event.title}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{meta.label}</div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span className={`badge badge-${event.severity === 'danger' ? 'danger' : event.severity === 'warning' ? 'warning' : event.severity === 'success' ? 'success' : 'info'}`}>{event.severity}</span>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>{new Date(event.created_at).toLocaleString()}</div>
                  </div>
                </div>
                {event.ref_id && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 8 }}>Reference: {event.ref_id}</div>}
                {event.detail && (
                  <pre style={{ margin: 0, background: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, fontSize: 12, color: '#334155', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(event.detail, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* Live Command Page */
