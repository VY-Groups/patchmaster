import React, { useState, useEffect } from 'react';

export function SchedulesPage({ API, apiFetch }) {
  const [schedules, setSchedules] = useState([]);
  const [groups, setGroups] = useState([]);
  const [form, setForm] = useState({ group_id:'', cron_expression:'0 2 * * SAT', action:'upgrade', auto_snapshot:true, auto_rollback:true, auto_reboot:false });

  const refresh = () => { apiFetch(`${API}/api/schedules/`).then(r=>r.json()).then(setSchedules).catch(()=>{}); };
  useEffect(()=>{ refresh(); apiFetch(`${API}/api/groups/`).then(r=>r.json()).then(setGroups).catch(()=>{}); },[]);

  const create = () => {
    if(!form.group_id) return alert('Select a group');
    apiFetch(`${API}/api/schedules/`, { method:'POST', body:JSON.stringify({...form,group_id:parseInt(form.group_id)}) }).then(()=>{refresh();setForm({group_id:'',cron_expression:'0 2 * * SAT',action:'upgrade',auto_snapshot:true,auto_rollback:true,auto_reboot:false});});
  };
  const del = id => { if(!window.confirm('Delete schedule?'))return; apiFetch(`${API}/api/schedules/${id}`,{method:'DELETE'}).then(refresh); };
  const toggle = async (id, enabled) => { await apiFetch(`${API}/api/schedules/${id}`,{method:'PUT',body:JSON.stringify({is_active:!enabled})}); refresh(); };

  return (
    <div>
      <div className="card"><h3>Create Schedule</h3>
        <div className="form-row">
          <select className="input" value={form.group_id} onChange={e=>setForm(f=>({...f,group_id:e.target.value}))}>
            <option value="">-- Select Group --</option>{groups.map(g=><option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <input className="input" placeholder="Cron (e.g. 0 2 * * SAT)" value={form.cron_expression} onChange={e=>setForm(f=>({...f,cron_expression:e.target.value}))} />
          <select className="input" value={form.action} onChange={e=>setForm(f=>({...f,action:e.target.value}))}><option value="upgrade">Upgrade</option><option value="server_patch">Server Patch</option></select>
          <button className="btn btn-primary" onClick={create}>Create</button>
        </div>
        <div className="options-grid" style={{marginTop:10}}>
          <label className="toggle-option"><input type="checkbox" checked={form.auto_snapshot} onChange={e=>setForm(f=>({...f,auto_snapshot:e.target.checked}))} /> Auto-Snapshot</label>
          <label className="toggle-option"><input type="checkbox" checked={form.auto_rollback} onChange={e=>setForm(f=>({...f,auto_rollback:e.target.checked}))} /> Auto-Rollback</label>
          <label className="toggle-option"><input type="checkbox" checked={form.auto_reboot} onChange={e=>setForm(f=>({...f,auto_reboot:e.target.checked}))} /> Auto-Reboot</label>
        </div>
      </div>
      <div className="card"><h3>Schedules ({schedules.length})</h3>
        {schedules.length===0?<p className="text-muted">No schedules created.</p>:(
          <table className="table"><thead><tr><th>Group</th><th>Cron</th><th>Action</th><th>Snapshot</th><th>Rollback</th><th>Enabled</th><th>Next Run</th><th>Actions</th></tr></thead>
            <tbody>{schedules.map(s=><tr key={s.id}><td><strong>{s.group_name||s.group_id}</strong></td><td><code>{s.cron_expression}</code></td><td>{s.action}</td><td>{s.auto_snapshot ? <span className="badge badge-success">Yes</span> : <span className="badge badge-warning">No</span>}</td><td>{s.auto_rollback ? <span className="badge badge-success">Yes</span> : <span className="badge badge-warning">No</span>}</td><td><button className={`btn btn-sm ${s.is_active?'btn-success':'btn-secondary'}`} onClick={()=>toggle(s.id,s.is_active)}>{s.is_active?'ON':'OFF'}</button></td><td>{s.next_run||'-'}</td><td><button className="btn btn-sm btn-danger" onClick={()=>del(s.id)}>Del</button></td></tr>)}</tbody></table>
        )}
      </div>
    </div>
  );
}
