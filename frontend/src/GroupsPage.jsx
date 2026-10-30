import React, { useState, useEffect } from 'react';

export function GroupsPage({ hosts, API, apiFetch, hasRole }) {
  const [groups, setGroups] = useState([]);
  const [tags, setTags] = useState([]);
  const [newGroup, setNewGroup] = useState('');
  const [newGroupDesc, setNewGroupDesc] = useState('');
  const [expandedGroup, setExpandedGroup] = useState(null);
  const [groupHosts, setGroupHosts] = useState([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedHosts, setSelectedHosts] = useState([]);

  const refresh = () => {
    apiFetch(`${API}/api/groups/`).then(r=>r.json()).then(setGroups).catch(()=>{});
    apiFetch(`${API}/api/tags/`).then(r=>r.json()).then(setTags).catch(()=>{});
  };
  useEffect(refresh, []);

  const createGroup = () => {
    if (!newGroup) return;
    apiFetch(`${API}/api/groups/`, { method:'POST', body: JSON.stringify({name:newGroup,description:newGroupDesc}) }).then(()=>{ setNewGroup(''); setNewGroupDesc(''); refresh(); });
  };
  const deleteGroup = id => { if(!window.confirm('Delete group?')) return; apiFetch(`${API}/api/groups/${id}`,{method:'DELETE'}).then(refresh); };

  const toggleExpand = async (id) => {
    if (expandedGroup===id) { setExpandedGroup(null); return; }
    try {
      const r = await apiFetch(`${API}/api/groups/${id}`);
      if (!r.ok) throw new Error('Failed to load group');
      const d = await r.json();
      setGroupHosts(d.hosts||[]); setExpandedGroup(id);
    } catch {
      setGroupHosts([]); setExpandedGroup(id);
    }
  };

  const addHostsToGroup = async () => {
    if (!expandedGroup || selectedHosts.length === 0) return;
    for (const hid of selectedHosts) {
      await apiFetch(`${API}/api/groups/${expandedGroup}/hosts/${hid}`, { method: 'POST' });
    }
    setShowAddModal(false); setSelectedHosts([]); toggleExpand(expandedGroup); refresh();
  };

  const removeHost = async (gid, hid) => {
    if(!window.confirm('Remove host from group?')) return;
    await apiFetch(`${API}/api/groups/${gid}/hosts/${hid}`, { method: 'DELETE' });
    toggleExpand(gid); refresh();
  };

  return (
    <div>
      <div className="card">
        <h3>Create Host Group</h3>
        <div className="form-row">
          <input className="input" placeholder="Group name" value={newGroup} onChange={e=>setNewGroup(e.target.value)} />
          <input className="input" placeholder="Description" value={newGroupDesc} onChange={e=>setNewGroupDesc(e.target.value)} style={{flex:1}} />
          <button className="btn btn-primary" onClick={createGroup}>Create Group</button>
        </div>
      </div>
      <div className="card">
        <h3>Groups ({groups.length})</h3>
        {groups.length===0 ? <p className="text-muted">No groups created.</p> : (
          <table className="table"><thead><tr><th>Name</th><th>Description</th><th>Hosts</th><th>Actions</th></tr></thead>
          <tbody>{groups.map(g=><React.Fragment key={g.id}>
            <tr><td><strong>{g.name}</strong></td><td>{g.description||'-'}</td><td>{g.host_count||0}</td>
            <td>
              <button className="btn btn-sm" onClick={()=>toggleExpand(g.id)}>{expandedGroup===g.id?'Collapse':'View Hosts'}</button>
              {hasRole('admin')&&<button className="btn btn-sm btn-danger" onClick={()=>deleteGroup(g.id)}>Del</button>}
            </td></tr>
            {expandedGroup===g.id && <tr><td colSpan="4">
              <div style={{padding:'12px',background:'#f8f9fa',borderRadius:6}}>
                <div style={{marginBottom:10, display:'flex', justifyContent:'space-between'}}>
                  <strong>Hosts in {g.name}:</strong>
                  <button className="btn btn-sm btn-primary" onClick={()=>setShowAddModal(true)}>Add Hosts</button>
                </div>
                {groupHosts.length===0 ? <p className="text-muted">No hosts in this group.</p> : (
                  <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
                    {groupHosts.map(h=>(
                      <span key={h.id} className="badge badge-info" style={{paddingRight:2}}>
                        {h.hostname} ({h.ip})
                        <button
                          style={{border:'none',background:'none',color:'#fff',marginLeft:4,cursor:'pointer'}}
                          title="Remove host"
                          aria-label={`Remove ${h.hostname} from ${g.name}`}
                          onClick={()=>removeHost(g.id, h.id)}
                        >
                          x
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </td></tr>}
          </React.Fragment>)}</tbody></table>
        )}
      </div>

      {showAddModal && (
        <div className="modal-overlay">
          <div className="modal-card">
            <h3>Add Hosts to Group</h3>
            <div style={{maxHeight:300, overflowY:'auto', margin:'10px 0'}}>
              {hosts.filter(h => !groupHosts.find(gh => gh.id === h.id)).map(h => (
                <div key={h.id} style={{padding:4}}>
                  <label>
                    <input type="checkbox" checked={selectedHosts.includes(h.id)}
                           onChange={e => setSelectedHosts(prev => e.target.checked ? [...prev, h.id] : prev.filter(id => id !== h.id))} />
                    <span style={{marginLeft:8}}>{h.hostname} ({h.ip})</span>
                  </label>
                </div>
              ))}
            </div>
            <div style={{textAlign:'right'}}>
              <button className="btn" onClick={()=>setShowAddModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={addHostsToGroup}>Add Selected</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
