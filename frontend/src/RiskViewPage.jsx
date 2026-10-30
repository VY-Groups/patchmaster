import React, { useEffect, useState } from 'react';

export default function RiskViewPage({ API, apiFetch }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch(`${API}/vulnerabilities?limit=50`);
        const data = await res.json();
        setItems(Array.isArray(data) ? data : (data.data || []));
      } catch (e) { setItems([]); }
    })();
  }, []);
  return (
    <div style={{ padding: 16 }}>
      <h2>Risk View (PMRS)</h2>
      {items.map((v, i) => (
        <div key={i} style={{ border: '1px solid var(--border-color)', padding: 8, marginBottom: 8 }}>
          <div><strong>{v.cve_id || v.id}</strong> score={v.pmrs || v.cvss_score}</div>
          <div>{v.title}</div>
        </div>
      ))}
      {items.length === 0 && <div>No vulnerabilities.</div>}
    </div>
  );
}