import React, { useEffect, useState } from 'react';

export default function EvidenceViewerPage({ API, apiFetch }) {
  const [bundles, setBundles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [jobId, setJobId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const qs = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
      const res = await apiFetch(`${API}/evidence/bundles${qs}`);
      const data = await res.json();
      setBundles(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const open = async (id) => {
    try {
      const res = await apiFetch(`${API}/evidence/bundles/${id}`);
      setSelected(await res.json());
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div style={{ padding: 16 }}>
      <h2>Evidence Viewer</h2>
      <div style={{ marginBottom: 12 }}>
        <input value={jobId} onChange={(e) => setJobId(e.target.value)} placeholder="job id filter" />
        <button onClick={load} disabled={loading}>Load</button>
      </div>
      {error && <div style={{ color: 'red' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <h3>Bundles</h3>
          {bundles.map((b) => (
            <div key={b.id} style={{ border: '1px solid var(--border-color)', padding: 8, marginBottom: 8, cursor: 'pointer' }} onClick={() => open(b.id)}>
              <div><strong>#{b.id}</strong> job={b.job_id}</div>
              <div>hash: {b.bundle_hash}</div>
              <div>items: {b.item_count} {b.signature ? '(signed)' : '(unsigned)'}</div>
            </div>
          ))}
          {!loading && bundles.length === 0 && <div>No bundles.</div>}
        </div>
        <div style={{ flex: 2 }}>
          {selected && (
            <div>
              <h3>Bundle #{selected.id}</h3>
              <div>job: {selected.job_id}</div>
              <div>hash: {selected.bundle_hash}</div>
              <div>prev: {selected.previous_bundle_hash || '(none)'}</div>
              <div>signature: {selected.signature || '(unsigned)'}</div>
              <h4>Items</h4>
              {selected.items.map((it) => (
                <div key={it.id} style={{ borderBottom: '1px solid var(--border-color)', padding: 4 }}>
                  <div>{it.step} — {it.kind}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>hash: {it.payload_hash}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}