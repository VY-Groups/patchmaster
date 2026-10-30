import React, { useState } from 'react';

export default function AddAssetWizardPage({ API, apiFetch }) {
  const [ip, setIp] = useState('');
  const [mode, setMode] = useState('agent');
  const [msg, setMsg] = useState('');
  const submit = async () => {
    try {
      const res = await apiFetch(`${API}/hosts`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip, mode }) });
      setMsg(res.ok ? 'Asset added' : 'Failed');
    } catch (e) { setMsg(String(e)); }
  };
  return (
    <div style={{ padding: 16 }}>
      <h2>Add Asset Wizard</h2>
      <div><input value={ip} onChange={(e) => setIp(e.target.value)} placeholder="IP or CIDR" /></div>
      <div>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="agent">Agent</option>
          <option value="agentless">Agentless</option>
          <option value="both">Both</option>
        </select>
      </div>
      <button onClick={submit}>Add</button>
      {msg && <div>{msg}</div>}
    </div>
  );
}