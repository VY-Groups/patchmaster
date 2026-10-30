import React, { useState } from 'react';

export function ComparePackagesPage({ hosts, API, apiFetch, sanitizeDisplayText, AppIcon }) {
  const [selectedHost, setSelectedHost] = useState('');
  const [installed, setInstalled] = useState([]);
  const [upgradable, setUpgradable] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [view, setView] = useState('all');

  const fetchData = async () => {
    if (!selectedHost) return alert('Select a host first');
    setLoading(true); setInstalled([]); setUpgradable([]);
    try {
      const [rI, rU] = await Promise.all([apiFetch(`${API}/api/agent/${selectedHost}/packages/installed`), apiFetch(`${API}/api/agent/${selectedHost}/packages/upgradable`)]);
      setInstalled((await rI.json()).packages||[]); setUpgradable((await rU.json()).packages||[]);
    } catch(e) { alert('Could not reach agent: '+e.message); }
    setLoading(false);
  };

  const upgMap = {}; upgradable.forEach(p=>{upgMap[p.name]=p;});
  const merged = installed.map(p=>({name:p.name,installed_version:p.version,available_version:upgMap[p.name]?.available_version||null,has_update:!!upgMap[p.name]}));
  const filtered = merged.filter(p=>{if(view==='upgradable'&&!p.has_update)return false;if(view==='uptodate'&&p.has_update)return false;if(search&&!p.name.toLowerCase().includes(search.toLowerCase()))return false;return true;});

  return (
    <div>
      <div className="card highlight-card"><h3><span style={{ display: 'inline-flex', marginRight: 8, verticalAlign: 'middle' }}><AppIcon name="search" size={16} /></span>Package Comparison</h3><p>Compare installed vs available package versions.</p></div>
      <div className="card"><div className="form-row">
        <select className="input" value={selectedHost} onChange={e=>setSelectedHost(e.target.value)}><option value="">-- Select Host --</option>{hosts.map(h=><option key={h.id} value={h.ip}>{h.hostname||h.name} ({h.ip})</option>)}</select>
        <button className="btn btn-primary" onClick={fetchData} disabled={loading}>{loading ? 'Scanning...' : 'Scan'}</button>
      </div></div>
      {installed.length>0 && <>
        <div className="stats-grid">
          <div className="stat-card" onClick={()=>setView('all')}><div className="stat-icon">PK</div><div className="stat-info"><span className="stat-number">{installed.length}</span><span className="stat-label">Installed</span></div></div>
          <div className="stat-card warning" onClick={()=>setView('upgradable')}><div className="stat-icon">UP</div><div className="stat-info"><span className="stat-number">{upgradable.length}</span><span className="stat-label">Updates</span></div></div>
          <div className="stat-card success" onClick={()=>setView('uptodate')}><div className="stat-icon"><AppIcon name="shield" size={20} /></div><div className="stat-info"><span className="stat-number">{installed.length-upgradable.length}</span><span className="stat-label">Up-to-date</span></div></div>
        </div>
        <div className="card"><div className="card-header"><h3>Packages ({filtered.length})</h3><input className="input search-input" placeholder="Search..." value={search} onChange={e=>setSearch(e.target.value)} /></div>
          <div className="package-list"><table className="table"><thead><tr><th>Package</th><th>Installed</th><th>Available</th><th>Status</th></tr></thead>
          <tbody>{filtered.slice(0,200).map((p,i)=><tr key={i} className={p.has_update?'row-update':''}><td><strong>{p.name}</strong></td><td><code>{sanitizeDisplayText(p.installed_version, '-')}</code></td><td>{p.available_version?<code className="text-success-inline">{sanitizeDisplayText(p.available_version, '-')}</code>:<span className="text-muted">-</span>}</td><td>{p.has_update?<span className="badge badge-warning">Update</span>:<span className="badge badge-success">OK</span>}</td></tr>)}</tbody></table>
          {filtered.length>200&&<p className="text-muted">Showing first 200. Use search to filter.</p>}</div>
        </div>
      </>}
    </div>
  );
}
