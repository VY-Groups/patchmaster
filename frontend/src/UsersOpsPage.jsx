import React, { useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

export default function UsersOpsPage({ API, apiFetch, AppIcon }) {
  const [users, setUsers] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newUser, setNewUser] = useState({username:'',email:'',password:'',full_name:'',role:'viewer'});
  const [createMsg, setCreateMsg] = useState('');
  const [resetPw, setResetPw] = useState({userId:null,password:''});
  const [resetMsg, setResetMsg] = useState('');
  const [editUser, setEditUser] = useState(null);
  const [editUserMsg, setEditUserMsg] = useState('');
  const [editPermsUser, setEditPermsUser] = useState(null);
  const [editPerms, setEditPerms] = useState({});
  const [permsMsg, setPermsMsg] = useState('');
  const [roleDefaults, setRoleDefaults] = useState(null);
  const [allFeatures, setAllFeatures] = useState([]);
  const [viewTab, setViewTab] = useState('users');
  const [ldapStatus, setLdapStatus] = useState(null);
  const [ldapConfig, setLdapConfig] = useState({
    server: '', base_dn: '', bind_dn: '', bind_password: '',
    user_search_filter: '(sAMAccountName={username})',
    admin_group_dn: '', operator_group_dn: '',
    use_ssl: false, verify_ssl: true, timeout: 10,
  });
  const [ldapTestResult, setLdapTestResult] = useState(null);
  const [ldapSyncing, setLdapSyncing] = useState(false);
  const [ldapTesting, setLdapTesting] = useState(false);
  const [ldapMsg, setLdapMsg] = useState('');

  const refresh = () => { apiFetch(`${API}/api/auth/users`).then(r=>r.json()).then(setUsers).catch(()=>{}); };
  useEffect(() => {
    refresh();
    apiFetch(`${API}/api/auth/role-defaults`).then(r=>r.json()).then(d => {
      setRoleDefaults(d.role_defaults);
      setAllFeatures(d.features);
    }).catch(()=>{});
    apiFetch(`${API}/api/auth/ldap/status`).then(r=>r.json()).then(setLdapStatus).catch(()=>{});
  }, []);

  const changeRole = async (id, role) => {
    await apiFetch(`${API}/api/auth/users/${id}`, { method:'PUT', body:JSON.stringify({role}) });
    refresh();
  };
  const toggleActive = async (id, is_active) => {
    await apiFetch(`${API}/api/auth/users/${id}`, { method:'PUT', body:JSON.stringify({is_active: !is_active}) });
    refresh();
  };
  const del = id => { if(!window.confirm('Delete this user? This cannot be undone.'))return; apiFetch(`${API}/api/auth/users/${id}`,{method:'DELETE'}).then(refresh); };
  const openEditUser = (u) => {
    setEditUser({ id: u.id, username: u.username, email: u.email || '', full_name: u.full_name || '' });
    setEditUserMsg('');
  };
  const saveEditUser = async () => {
    if(!editUser) return;
    setEditUserMsg('');
    try {
      const r = await apiFetch(`${API}/api/auth/users/${editUser.id}`, { method:'PUT', body: JSON.stringify({ email: editUser.email, full_name: editUser.full_name }) });
      const d = await r.json().catch(()=> ({}));
      if (r.ok) { setEditUser(null); refresh(); }
      else { setEditUserMsg(d.detail || 'Failed to update user'); }
    } catch (e) { setEditUserMsg(e.message); }
  };

  const createUser = async () => {
    setCreateMsg('');
    if(!newUser.username||!newUser.email||!newUser.password) { setCreateMsg('All fields are required'); return; }
    try {
      const r = await apiFetch(`${API}/api/auth/users`, { method:'POST', body:JSON.stringify(newUser) });
      const d = await r.json();
      if(r.ok) { setCreateMsg('User created successfully!'); setNewUser({username:'',email:'',password:'',full_name:'',role:'viewer'}); setShowCreate(false); refresh(); }
      else { setCreateMsg(d.detail||'Failed to create user'); }
    } catch(e) { setCreateMsg('Error: '+e.message); }
  };

  const adminResetPassword = async () => {
    setResetMsg('');
    if(!resetPw.password) { setResetMsg('Enter a new password'); return; }
    try {
      const r = await apiFetch(`${API}/api/auth/users/${resetPw.userId}/reset-password`, { method:'POST', body:JSON.stringify({new_password:resetPw.password}) });
      const d = await r.json();
      if(r.ok) { setResetMsg('Password reset!'); setResetPw({userId:null,password:''}); }
      else { setResetMsg(d.detail||'Failed'); }
    } catch(e) { setResetMsg('Error: '+e.message); }
  };

  const openPermsEditor = (u) => {
    setEditPermsUser(u);
    setEditPerms(u.effective_permissions || {});
    setPermsMsg('');
  };
  const togglePerm = (feat) => {
    setEditPerms(p => ({...p, [feat]: !p[feat]}));
  };
  const savePerms = async () => {
    setPermsMsg('');
    if(!editPermsUser) return;
    // Send the full permissions map — backend stores only the overrides
    const permsToSave = {};
    const safeAllFeatures = Array.isArray(allFeatures) ? allFeatures : [];
    for(const f of safeAllFeatures) {
      permsToSave[f] = !!editPerms[f];
    }
    try {
      const r = await apiFetch(`${API}/api/auth/users/${editPermsUser.id}/permissions`, {
        method:'PUT',
        body: JSON.stringify({ permissions: permsToSave })
      });
      if(r.ok) {
        setPermsMsg('Permissions saved!');
        refresh();
      } else {
        const d = await r.json().catch(() => ({}));
        setPermsMsg(d.detail || 'Failed to save permissions');
      }
    } catch(e) {
      setPermsMsg('Error: ' + e.message);
    }
  };
  const resetPermsToRole = () => {
    if(editPermsUser && roleDefaults) {
      setEditPerms({...roleDefaults[editPermsUser.role]});
    }
  };

  const testLdap = async () => {
    setLdapTesting(true); setLdapTestResult(null); setLdapMsg('');
    try {
      const r = await apiFetch(`${API}/api/auth/ldap/test`, { method: 'POST', body: JSON.stringify({ config: ldapConfig }) });
      const d = await r.json().catch(() => ({}));
      setLdapTestResult(d);
    } catch(e) { setLdapTestResult({ ok: false, message: e.message }); }
    setLdapTesting(false);
  };

  const syncLdap = async () => {
    if (!window.confirm('Sync all AD users? This will create/update local accounts.')) return;
    setLdapSyncing(true); setLdapMsg('');
    try {
      const r = await apiFetch(`${API}/api/auth/ldap/sync`, { method: 'POST', body: JSON.stringify({ config: ldapConfig, default_role: 'viewer' }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok) { setLdapMsg(`Sync complete: ${d.created} created, ${d.updated} updated, ${d.skipped} skipped.`); refresh(); }
      else { setLdapMsg(d.detail || 'Sync failed'); }
    } catch(e) { setLdapMsg('Error: ' + e.message); }
    setLdapSyncing(false);
  };

  const featureLabels = {
    dashboard:'Dashboard', compliance:'Compliance', hosts:'Hosts', groups:'Groups & Tags',
    patches:'Patch Manager', snapshots:'Snapshots', compare:'Compare Packages', offline:'Offline Patching',
    schedules:'Schedules', cve:'CVE Tracker', jobs:'Job History', audit:'Audit Trail',
    notifications:'Notifications', users:'User Management', license:'License', onboarding:'Onboarding', settings:'Settings',
    monitoring:'Monitoring Tools', testing:'Testing Center', cicd:'CI/CD Pipelines', git:'Git Integration',
    cicd_view:'CI/CD View', cicd_manage:'CI/CD Manage', cicd_execute:'CI/CD Execute', cicd_approve:'CI/CD Approve',
    'local-repo':'Local Repository', software:'Software Manager', policies:'Config Policies', reports:'Reports',
    backups:'Backup & Recovery', backup_db:'Database Backup', backup_file:'File Backup', backup_vm:'VM Backup', backup_live:'Live Backup',
    wsus:'WSUS / Windows Updates',
  };

  // Defensive array checks
  const safeUsers = Array.isArray(users) ? users : [];
  const safeAllFeatures = Array.isArray(allFeatures) ? allFeatures : [];

  const activeUsers = safeUsers.filter((user) => user.is_active).length;
  const customOverrideUsers = safeUsers.filter((user) => Object.keys(user.custom_permissions || {}).length > 0).length;
  const roleMix = useMemo(() => ({
    admin: safeUsers.filter((user) => user.role === 'admin').length,
    operator: safeUsers.filter((user) => user.role === 'operator').length,
    viewer: safeUsers.filter((user) => user.role === 'viewer').length,
    auditor: safeUsers.filter((user) => user.role === 'auditor').length,
  }), [safeUsers]);

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#06b6d4', background: 'linear-gradient(145deg, #f5f3ff, #faf9ff)' }}>
          <div className="ops-kicker">Identity and access</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Active users</span>
              <span className="ops-emphasis-value" style={{ color: '#06b6d4' }}>{activeUsers}</span>
              <span className="ops-emphasis-meta">{users.length} total accounts across admins, operators, viewers, and auditors.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Run user administration and RBAC from one clean workspace.</h3>
              <p>
                This view now feels more like a real access governance console: quick visibility into account health, role distribution, and custom permission overrides, with creation, password reset, and per-user access controls still intact.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">{roleMix.admin} admins</span>
            <span className="ops-chip">{roleMix.operator} operators</span>
            <span className="ops-chip">{roleMix.viewer} viewers</span>
            <span className="ops-chip">{roleMix.auditor} auditors</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Access posture</span>
          <div className="ops-side-metric">{customOverrideUsers}</div>
          <p className="ops-side-note">
            Users with custom overrides deserve the most attention during access reviews because their effective permissions differ from role defaults.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>{safeUsers.length}</strong>
              <span>total accounts</span>
            </div>
            <div className="ops-inline-card">
              <strong>{activeUsers}</strong>
              <span>enabled users</span>
            </div>
            <div className="ops-inline-card">
              <strong>{safeAllFeatures.length}</strong>
              <span>feature entitlements</span>
            </div>
            <div className="ops-inline-card">
              <strong>{customOverrideUsers}</strong>
              <span>custom overrides</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {[
          { label: 'Enabled accounts', value: activeUsers, sub: 'users currently allowed to sign in', icon: 'users', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
          { label: 'Custom overrides', value: customOverrideUsers, sub: 'accounts with permission deltas from role defaults', icon: 'shield', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
          { label: 'Admin coverage', value: roleMix.admin, sub: 'accounts with highest privilege tier', icon: 'key', color: '#dc2626', bg: 'rgba(239,68,68,0.12)' },
          { label: 'Feature matrix', value: safeAllFeatures.length, sub: 'permissions tracked by Patch-SecOps Solution RBAC', icon: 'sliders', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
        ].map((card) => (
          <div key={card.label} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.label}</span>
            </div>
            <div className="ops-summary-value">{card.value}</div>
            <div className="ops-summary-sub">{card.sub}</div>
          </div>
        ))}
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Workspace</div>
            <p className="ops-subtle">Switch between day-to-day user administration, the RBAC baseline, and per-user overrides.</p>
          </div>
        </div>
        <div className="ops-pills">
          {[{k:'users',l:'Users'},{k:'permissions',l:'RBAC Matrix'},{k:'peruser',l:'Per-User Permissions'},{k:'ldap',l:'AD / LDAP'}].map(t=>(
            <button key={t.k} className={`ops-pill ${viewTab===t.k?'active':''}`} onClick={()=>setViewTab(t.k)}>{t.l}</button>
          ))}
        </div>
      </div>

      {/* ── TAB 1: Users List ── */}
      {viewTab === 'users' && (<>
        {/* Create User */}
        <div className="card">
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <h3>Users ({safeUsers.length})</h3>
            <button className="btn btn-primary" onClick={()=>setShowCreate(!showCreate)}>{showCreate?'Cancel':'+ New User'}</button>
          </div>
          {showCreate && (
            <div style={{marginTop:16,padding:16,background:'rgba(255,255,255,0.05)',borderRadius:8}}>
              <h4 style={{marginBottom:12}}>Create New User</h4>
              <div className="form-row" style={{flexWrap:'wrap',gap:8}}>
                <input className="input" placeholder="Username *" value={newUser.username} onChange={e=>setNewUser(f=>({...f,username:e.target.value}))} style={{minWidth:150}} />
                <input className="input" type="email" placeholder="Email *" value={newUser.email} onChange={e=>setNewUser(f=>({...f,email:e.target.value}))} style={{minWidth:200}} />
                <input className="input" type="password" placeholder="Password * (min 8 chars)" value={newUser.password} onChange={e=>setNewUser(f=>({...f,password:e.target.value}))} style={{minWidth:180}} />
                <input className="input" placeholder="Full Name" value={newUser.full_name} onChange={e=>setNewUser(f=>({...f,full_name:e.target.value}))} style={{minWidth:150}} />
                <select className="input" value={newUser.role} onChange={e=>setNewUser(f=>({...f,role:e.target.value}))}>
                  <option value="admin">Admin</option><option value="operator">Operator</option><option value="viewer">Viewer</option><option value="auditor">Auditor</option>
                </select>
                <button className="btn btn-primary" onClick={createUser}>Create User</button>
              </div>
              {createMsg && <p style={{marginTop:8,fontWeight:500,color:createMsg.includes('success')?'#28a745':'#dc3545'}}>{createMsg}</p>}
            </div>
          )}
        </div>

        {/* Users Table */}
        <div className="card">
          <table className="table">
            <thead><tr><th>Username</th><th>Email</th><th>Full Name</th><th>Role</th><th>Active</th><th>Created</th><th>Actions</th></tr></thead>
            <tbody>{safeUsers.map(u=><tr key={u.id}>
              <td><strong>{u.username}</strong></td>
              <td>{u.email||'—'}</td>
              <td>{u.full_name||'—'}</td>
              <td>
                <select className="input input-sm" value={u.role} onChange={e=>changeRole(u.id,e.target.value)} style={{minWidth:100}}>
                  <option value="admin">Admin</option><option value="operator">Operator</option><option value="viewer">Viewer</option><option value="auditor">Auditor</option>
                </select>
              </td>
              <td>
                <button className={`btn btn-sm ${u.is_active?'btn-success':'btn-danger'}`} onClick={()=>toggleActive(u.id,u.is_active)} style={{minWidth:70}}>
                  {u.is_active?'Active':'Disabled'}
                </button>
              </td>
              <td>{u.created_at?new Date(u.created_at).toLocaleDateString():'—'}</td>
              <td style={{display:'flex',gap:4,flexWrap:'wrap'}}>
                <button className="btn btn-sm" onClick={()=>openEditUser(u)}>Edit</button>
                <button className="btn btn-sm btn-info" onClick={()=>{openPermsEditor(u);setViewTab('peruser');}}>Perms</button>
                <button className="btn btn-sm btn-warning" onClick={()=>{setResetPw({userId:u.id,password:''});setResetMsg('');}}>Reset PW</button>
                <button className="btn btn-sm btn-danger" onClick={()=>del(u.id)}>Delete</button>
              </td>
            </tr>)}</tbody>
          </table>
        </div>

        {editUser && (
          <div className="modal-overlay">
            <div className="modal-card" style={{maxWidth:560}}>
              <h3>Edit User: {editUser.username}</h3>
              {editUserMsg && <div className="alert alert-danger">{editUserMsg}</div>}
              <div className="form-row">
                <label>Email</label>
                <input className="input" type="email" value={editUser.email} onChange={e=>setEditUser(s=>({...s,email:e.target.value}))} />
              </div>
              <div className="form-row">
                <label>Full Name</label>
                <input className="input" value={editUser.full_name} onChange={e=>setEditUser(s=>({...s,full_name:e.target.value}))} />
              </div>
              <div style={{display:'flex',gap:8,justifyContent:'flex-end',marginTop:12}}>
                <button className="btn" onClick={()=>setEditUser(null)}>Cancel</button>
                <button className="btn btn-primary" onClick={saveEditUser}>Save</button>
              </div>
            </div>
          </div>
        )}

        {/* Reset Password Panel */}
        {resetPw.userId && (
          <div className="card" style={{border:'2px solid #ffc107'}}>
            <h3>Reset Password for: {safeUsers.find(u=>u.id===resetPw.userId)?.username}</h3>
            <div className="form-row">
              <input className="input" type="password" placeholder="New password (min 8 chars)" value={resetPw.password} onChange={e=>setResetPw(f=>({...f,password:e.target.value}))} />
              <button className="btn btn-warning" onClick={adminResetPassword}>Reset Password</button>
              <button className="btn" onClick={()=>setResetPw({userId:null,password:''})}>Cancel</button>
            </div>
            {resetMsg && <p style={{marginTop:8,fontWeight:500,color:resetMsg.includes('reset')?'#28a745':'#dc3545'}}>{resetMsg}</p>}
          </div>
        )}
      </>)}

      {/* ── TAB 2: RBAC Permissions Matrix ── */}
      {viewTab === 'permissions' && (
        <div className="card">
          <h3>Role-Based Access Control (RBAC) Matrix</h3>
          <p style={{color:'#9ca3af',marginBottom:12}}>Shows default permissions for each role. Admin can override per user in the "Per-User Permissions" tab.</p>
          {roleDefaults ? (
            <div style={{overflowX:'auto'}}>
              <table className="table">
                <thead>
                  <tr>
                    <th style={{minWidth:180}}>Feature</th>
                    <th style={{textAlign:'center'}}>Admin</th>
                    <th style={{textAlign:'center'}}>Operator</th>
                    <th style={{textAlign:'center'}}>Viewer</th>
                    <th style={{textAlign:'center'}}>Auditor</th>
                  </tr>
                </thead>
                <tbody>
                  {safeAllFeatures.map(f => (
                    <tr key={f}>
                      <td><strong>{featureLabels[f]||f}</strong></td>
                      {['admin','operator','viewer','auditor'].map(role => (
                        <td key={role} style={{textAlign:'center'}}>
                          {roleDefaults[role]?.[f] ? <span className="badge badge-success">Yes</span> : <span className="badge badge-warning">No</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p>Loading...</p>}

          {/* Per-user effective permissions */}
          <h3 style={{marginTop:24}}>All Users — Effective Permissions</h3>
          <p style={{color:'#9ca3af',marginBottom:12}}>Shows actual permissions per user (role defaults + custom overrides). Custom overrides shown in <span style={{color:'#f39c12',fontWeight:600}}>orange</span>.</p>
          {safeUsers.length > 0 && safeAllFeatures.length > 0 && (
            <div style={{overflowX:'auto'}}>
              <table className="table">
                <thead>
                  <tr>
                    <th style={{minWidth:120}}>Feature</th>
                    {safeUsers.map(u => <th key={u.id} style={{textAlign:'center',minWidth:80}}><div>{u.username}</div><div style={{fontSize:10,color:'#9ca3af'}}>({u.role})</div></th>)}
                  </tr>
                </thead>
                <tbody>
                  {safeAllFeatures.map(f => (
                    <tr key={f}>
                      <td><strong>{featureLabels[f]||f}</strong></td>
                      {safeUsers.map(u => {
                        const ep = u.effective_permissions || {};
                        const hasCustom = u.custom_permissions && u.custom_permissions[f] !== undefined;
                        return (
                          <td key={u.id} style={{textAlign:'center', background: hasCustom ? 'rgba(243,156,18,0.1)' : 'transparent'}}>
                            {ep[f] ? <span className="badge badge-success" style={{background: hasCustom ? '#f39c12' : undefined}}>Yes</span> : <span className="badge badge-warning">No</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── TAB 3: Per-User Permissions Editor ── */}
      {viewTab === 'peruser' && (
        <div>
          {!editPermsUser ? (
            <div className="card">
              <h3>Per-User Permissions</h3>
              <p style={{color:'#9ca3af'}}>Select a user to customize their feature access beyond their role defaults.</p>
              <div style={{display:'flex',flexWrap:'wrap',gap:8,marginTop:12}}>
                {safeUsers.map(u => (
                  <button key={u.id} className="btn" onClick={()=>openPermsEditor(u)} style={{minWidth:120}}>
                    <strong>{u.username}</strong><br/><span style={{fontSize:11,color:'#9ca3af'}}>{u.role}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="card" style={{border:'2px solid #3b82f6'}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:8}}>
                <h3>Permissions for: {editPermsUser.username} <span className="badge badge-info">{editPermsUser.role}</span></h3>
                <div style={{display:'flex',gap:8}}>
                  <button className="btn" onClick={resetPermsToRole}>Reset to Role Defaults</button>
                  <button className="btn btn-primary" onClick={savePerms}>Save Permissions</button>
                  <button className="btn" onClick={()=>{setEditPermsUser(null);setPermsMsg('');}}>Close</button>
                </div>
              </div>
              {permsMsg && <p style={{marginTop:8,fontWeight:500,color:permsMsg.includes('saved')?'#28a745':'#dc3545'}}>{permsMsg}</p>}
              <p style={{color:'#9ca3af',margin:'8px 0'}}>Toggle features ON/OFF for this user. Changes override their role defaults.</p>
              <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(200px,1fr))',gap:8,marginTop:12}}>
                {safeAllFeatures.map(f => {
                  const isOn = !!editPerms[f];
                  const roleDef = roleDefaults ? !!roleDefaults[editPermsUser.role]?.[f] : false;
                  const isOverride = isOn !== roleDef;
                  return (
                    <div key={f} onClick={()=>togglePerm(f)} style={{
                      padding:'10px 14px', borderRadius:8, cursor:'pointer', display:'flex', alignItems:'center', gap:10,
                      background: isOn ? 'rgba(40,167,69,0.15)' : 'rgba(108,117,125,0.1)',
                      border: isOverride ? '2px solid #f39c12' : '2px solid transparent',
                    }}>
                      <span className={`badge ${isOn ? 'badge-success' : 'badge-warning'}`}>{isOn ? 'On' : 'Off'}</span>
                      <div>
                        <div style={{fontWeight:600}}>{featureLabels[f]||f}</div>
                        {isOverride && <div style={{fontSize:10,color:'#f39c12'}}>Custom override</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
      {/* ── TAB 4: AD / LDAP Integration ── */}
      {viewTab === 'ldap' && (
        <div>
          <div className="card" style={{ borderLeft: '4px solid #3b82f6' }}>
            <h3>Active Directory / LDAP Integration</h3>
            <p style={{ color: '#64748b', marginBottom: 16 }}>
              Configure AD/LDAP so users can log in with their domain credentials. Roles are mapped from AD group membership.
              Set these values as environment variables on the server for persistent config, or test here.
            </p>

            {ldapStatus && (
              <div style={{ marginBottom: 16, padding: '10px 14px', borderRadius: 8, background: ldapStatus.configured ? 'rgba(34,197,94,0.1)' : 'rgba(245,158,11,0.1)', border: `1px solid ${ldapStatus.configured ? '#22c55e' : '#f59e0b'}` }}>
                <strong>{ldapStatus.configured ? 'LDAP configured via environment variables' : 'LDAP not configured — set LDAP_SERVER env var or fill the form below'}</strong>
                {ldapStatus.configured && <div style={{ fontSize: 12, marginTop: 4, color: '#64748b' }}>Server: {ldapStatus.server} · Base DN: {ldapStatus.base_dn}</div>}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              {[
                ['server', 'LDAP Server URL', 'ldap://dc.corp.local or ldaps://dc.corp.local:636'],
                ['base_dn', 'Base DN', 'DC=corp,DC=local'],
                ['bind_dn', 'Service Account DN', 'CN=svc-patchmaster,OU=ServiceAccounts,DC=corp,DC=local'],
                ['bind_password', 'Service Account Password', ''],
                ['user_search_filter', 'User Search Filter', '(sAMAccountName={username})'],
                ['admin_group_dn', 'Admin Group DN (optional)', 'CN=PatchMaster-Admins,OU=Groups,DC=corp,DC=local'],
                ['operator_group_dn', 'Operator Group DN (optional)', 'CN=PatchMaster-Operators,OU=Groups,DC=corp,DC=local'],
              ].map(([key, label, placeholder]) => (
                <div key={key}>
                  <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>{label}</label>
                  <input
                    className="input"
                    type={key === 'bind_password' ? 'password' : 'text'}
                    placeholder={placeholder}
                    value={ldapConfig[key] || ''}
                    onChange={e => setLdapConfig(c => ({ ...c, [key]: e.target.value }))}
                    style={{ width: '100%' }}
                  />
                </div>
              ))}
              <div style={{ display: 'flex', gap: 16, alignItems: 'center', paddingTop: 20 }}>
                <label className="toggle-option">
                  <input type="checkbox" checked={ldapConfig.use_ssl} onChange={e => setLdapConfig(c => ({ ...c, use_ssl: e.target.checked }))} />
                  Use SSL (ldaps://)
                </label>
                <label className="toggle-option">
                  <input type="checkbox" checked={ldapConfig.verify_ssl} onChange={e => setLdapConfig(c => ({ ...c, verify_ssl: e.target.checked }))} />
                  Verify SSL certificate
                </label>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
              <button className="btn btn-primary" onClick={testLdap} disabled={ldapTesting || !ldapConfig.server}>
                {ldapTesting ? 'Testing...' : 'Test Connection'}
              </button>
              <button className="btn btn-warning" onClick={syncLdap} disabled={ldapSyncing || !ldapConfig.server}>
                {ldapSyncing ? 'Syncing...' : 'Sync All AD Users'}
              </button>
            </div>

            {ldapTestResult && (
              <div style={{ padding: '10px 14px', borderRadius: 8, marginBottom: 8, background: ldapTestResult.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)', border: `1px solid ${ldapTestResult.ok ? '#22c55e' : '#ef4444'}` }}>
                <strong>{ldapTestResult.ok ? 'OK: ' : 'Failed: '}{ldapTestResult.message}</strong>
              </div>
            )}
            {ldapMsg && <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(59,130,246,0.1)', border: '1px solid #3b82f6' }}>{ldapMsg}</div>}
          </div>

          <div className="card">
            <h3>How AD Login Works</h3>
            <ol style={{ color: '#64748b', lineHeight: 2, paddingLeft: 20 }}>
              <li>User enters their AD username and password on the login page and clicks <strong>Sign in with AD</strong>.</li>
              <li>Patch-SecOps Solution binds to the LDAP server with the service account and searches for the user.</li>
              <li>The user's own credentials are verified against the directory.</li>
              <li>Their AD group membership is checked against the configured Admin/Operator group DNs to assign a role.</li>
              <li>A local account is created or updated automatically — no manual user creation needed.</li>
              <li>A JWT token is issued and the session proceeds identically to local login.</li>
            </ol>
            <div style={{ marginTop: 12, padding: '10px 14px', borderRadius: 8, background: 'rgba(245,158,11,0.08)', border: '1px solid #f59e0b' }}>
              <strong>Environment variables for persistent config:</strong>
              <pre style={{ fontSize: 12, marginTop: 8, color: '#64748b' }}>{`LDAP_SERVER=ldap://dc.corp.local
LDAP_BASE_DN=DC=corp,DC=local
LDAP_BIND_DN=CN=svc-pm,OU=ServiceAccounts,DC=corp,DC=local
LDAP_BIND_PASSWORD=your-service-account-password
LDAP_ADMIN_GROUP=CN=PatchMaster-Admins,OU=Groups,DC=corp,DC=local
LDAP_OPERATOR_GROUP=CN=PatchMaster-Operators,OU=Groups,DC=corp,DC=local
LDAP_USE_SSL=false
LDAP_VERIFY_SSL=true`}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── CI/CD Pipelines ─── */
