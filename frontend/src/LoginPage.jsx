import React, { useState } from 'react';

/* --- AD / LDAP Login Button --- */
function LdapLoginButton({ onLogin, API }) {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const r = await fetch(`${API}/api/auth/ldap/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const d = await r.json();
      if (!r.ok) {
        // If LDAP not configured, show a clear message instead of a generic error
        const msg = d?.detail || d?.error?.message || 'AD login failed';
        setError(msg);
        setLoading(false);
        return;
      }
      let me = d.user;
      try {
        const meRes = await fetch(`${API}/api/auth/me`, { headers: { 'Authorization': `Bearer ${d.access_token}` } });
        if (meRes.ok) me = await meRes.json();
      } catch {}
      onLogin(d.access_token, me);
    } catch {
      setError('Connection failed');
    }
    setLoading(false);
  };

  if (!open) {
    return (
      <button
        type="button"
        style={{ width: '100%', padding: 11, background: '#1e3a5f', border: '1px solid #2563eb', color: '#93c5fd', borderRadius: 8, cursor: 'pointer', fontWeight: 600, fontSize: 14 }}
        onClick={() => setOpen(true)}
      >
        Sign in with Active Directory
      </button>
    );
  }

  return (
    <form onSubmit={submit} style={{ padding: 12, border: '1px solid #2563eb', borderRadius: 8, background: '#0f172a' }}>
      <div style={{ color: '#93c5fd', fontWeight: 600, fontSize: 13, marginBottom: 10 }}>Active Directory Login</div>
      <input
        className="input"
        style={{ width: '100%', background: '#111827', border: '1px solid #334155', color: '#fff', padding: 9, borderRadius: 7, marginBottom: 8 }}
        placeholder="Domain username (e.g. jsmith)"
        value={username}
        onChange={e => setUsername(e.target.value)}
        required
      />
      <input
        className="input"
        type="password"
        style={{ width: '100%', background: '#111827', border: '1px solid #334155', color: '#fff', padding: 9, borderRadius: 7, marginBottom: 10 }}
        placeholder="Domain password"
        value={password}
        onChange={e => setPassword(e.target.value)}
        required
      />
      {error && <div style={{ background: '#7f1d1d', color: '#fca5a5', padding: 8, borderRadius: 6, fontSize: 12, marginBottom: 8 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="submit" style={{ flex: 1, padding: 9, background: '#2563eb', border: 'none', color: '#fff', borderRadius: 7, fontWeight: 600, cursor: 'pointer' }} disabled={loading}>
          {loading ? 'Authenticating...' : 'Sign In'}
        </button>
        <button type="button" style={{ padding: '9px 14px', background: 'transparent', border: '1px solid #334155', color: '#94a3b8', borderRadius: 7, cursor: 'pointer' }} onClick={() => { setOpen(false); setError(''); }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/* --- Login Page --- */
export function LoginPage({ onLogin, API }) {
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [fullName, setFullName] = React.useState('');
  const [error, setError] = React.useState('');
  const [isSetup, setIsSetup] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [resetMode, setResetMode] = React.useState(false);
  const [fpUser, setFpUser] = React.useState('');
  const [fpOtp, setFpOtp] = React.useState('');
  const [fpNewPwd, setFpNewPwd] = React.useState('');
  const [fpMsg, setFpMsg] = React.useState('');
  const [fpBusy, setFpBusy] = React.useState(false);

  React.useEffect(() => {
    fetch(`${API}/api/auth/setup/check`)
      .then(r => r.json())
      .then(d => setIsSetup(d.setup_required))
      .catch(() => setIsSetup(false));

    // Handle SSO callback token in URL fragment
    const hash = window.location.hash;
    if (hash && hash.includes('sso_token=')) {
      const p = new URLSearchParams(hash.replace('#', '?'));
      const t = p.get('sso_token');
      if (t) {
        window.location.hash = ''; // clear fragment
        onLogin(t, { username: 'SSO User' }); 
      }
    }
  }, [onLogin]);

  const validatePassword = (pw) => {
    if (pw.length < 12 || pw.length > 128) return "Password must be 12-128 characters.";
    if (!/[A-Z]/.test(pw)) return "Password needs an uppercase letter.";
    if (!/[a-z]/.test(pw)) return "Password needs a lowercase letter.";
    if (!/[0-9]/.test(pw)) return "Password needs a number.";
    if (!/[!@#$%^&*()\-_=+[\]{}|;:,.<>?/\\~`]/.test(pw)) return "Password needs a special character.";
    return null;
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');

    if (isSetup) {
      const pwErr = validatePassword(password);
      if (pwErr) { setError(pwErr); return; }
    }

    setLoading(true);
    try {
      if (isSetup) {
        const r = await fetch(`${API}/api/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password, email, full_name: fullName })
        });
        const d = await r.json();
        if (!r.ok) { setError(d.detail || 'Setup failed'); setLoading(false); return; }
        setIsSetup(false);
        setError('');
        alert('Admin account created! Please login now.');
      } else {
        const r = await fetch(`${API}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        const d = await r.json();
        if (!r.ok) { setError(d.detail || 'Login failed'); setLoading(false); return; }

        let me = d.user;
        try {
          const meRes = await fetch(`${API}/api/auth/me`, {
            headers: { 'Authorization': `Bearer ${d.access_token}` }
          });
          if (meRes.ok) me = await meRes.json();
        } catch {}
        onLogin(d.access_token, me);
      }
    } catch (e) {
      setError('Connection to Patch-SecOps Solution API failed');
    }
    setLoading(false);
  };

  const requestReset = async () => {
    if (!fpUser) { setFpMsg('Enter username or email'); return; }
    setFpBusy(true); setFpMsg('');
    try {
      const r = await fetch(`${API}/api/auth/forgot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username_or_email: fpUser })
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Reset request failed');
      setFpMsg('If that account exists and an email channel is configured, a 6-digit reset code was sent to its email address. Enter it below (valid 10 minutes) to set your new password.');
    } catch (e) { setFpMsg(e.message); }
    setFpBusy(false);
  };

  const performReset = async () => {
    const pwErr = validatePassword(fpNewPwd);
    if (pwErr) { setFpMsg(pwErr); return; }
    if (!fpUser) { setFpMsg('Enter username or email.'); return; }
    if (!/^\d{6}$/.test(fpOtp)) { setFpMsg('Enter the 6-digit code from your email.'); return; }
    setFpBusy(true); setFpMsg('');
    try {
      const r = await fetch(`${API}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username_or_email: fpUser, otp: fpOtp, new_password: fpNewPwd })
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Reset failed');
      setFpMsg('Password reset! You can now log in with the new password.');
      setResetMode(false);
      setPassword('');
    } catch (e) { setFpMsg(e.message); }
    setFpBusy(false);
  };

  return (
    <div className="login-container" style={{background:'#0f172a', height:'100vh', display:'flex', alignItems:'center', justifyContent:'center'}}>
      <div className="login-card" style={{background:'#1e293b', padding:'2.5rem', borderRadius:16, width:400, border:'1px solid #334155', boxShadow:'0 20px 25px -5px rgba(0,0,0,0.3)'}}>
        <h2 style={{color:'#fff', textAlign:'center', marginBottom:8}}>Patch-SecOps Solution</h2>
        <p style={{textAlign:'center', color:'#94a3b8', fontSize:14, marginBottom:24}}>
          {isSetup ? 'Welcome! Create the primary Administrator account.' : 'Sign in to your account'}
        </p>

        <form onSubmit={submit}>
          <div style={{marginBottom:16}}>
            <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Username</label>
            <input className="input" style={{width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8}}
              placeholder="e.g. admin" value={username} onChange={e=>setUsername(e.target.value)} required />
          </div>

          {isSetup && (
             <>
              <div style={{marginBottom:16}}>
                <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Email Address</label>
                <input className="input" type="email" style={{width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8}}
                  placeholder="admin@company.com" value={email} onChange={e=>setEmail(e.target.value)} required />
              </div>
              <div style={{marginBottom:16}}>
                <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Full Name (Optional)</label>
                <input className="input" style={{width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8}}
                  placeholder="Administrator" value={fullName} onChange={e=>setFullName(e.target.value)} />
              </div>
            </>
          )}

          <div style={{marginBottom:24}}>
            <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Password</label>
            <input className="input" type="password" style={{width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8}}
              placeholder="********" value={password} onChange={e=>setPassword(e.target.value)} required />
            {isSetup && <small style={{color:'#64748b', fontSize:11, marginTop:4, display:'block'}}>12-128 chars, mix of upper, lower, numbers & symbols</small>}
          </div>

          {error && <div style={{background:'#7f1d1d', color:'#fca5a5', padding:10, borderRadius:8, fontSize:13, marginBottom:16, border:'1px solid #dc2626'}}>{error}</div>}

          <button className="btn btn-primary btn-lg" style={{width:'100%', padding:12, fontWeight:600}} disabled={loading}>
            {loading ? 'Processing...' : isSetup ? 'Initialize System' : 'Sign In'}
          </button>
        </form>

        {!isSetup && (
          <div style={{marginTop:20}}>
            <div style={{display:'flex', alignItems:'center', gap:8, margin:'12px 0'}}>
              <div style={{flex:1, height:1, background:'#334155'}} />
              <span style={{color:'#475569', fontSize:12}}>OR</span>
              <div style={{flex:1, height:1, background:'#334155'}} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button 
                type="button" 
                onClick={() => window.location.href = `${API}/api/auth/oidc/login`}
                style={{ width: '100%', padding: 11, background: '#0ea5e9', border: '1px solid #0284c7', color: '#0f172a', borderRadius: 8, cursor: 'pointer', fontWeight: 600, fontSize: 14 }}>
                Enterprise SSO Login
              </button>
              <LdapLoginButton onLogin={onLogin} API={API} />
            </div>

            <div style={{marginTop:16, color:'#cbd5e1', fontSize:13}}>
              <button type="button" className="btn btn-sm" style={{width:'100%', background:'#0f172a', border:'1px solid #334155', color:'#cbd5e1'}} onClick={()=>setResetMode(!resetMode)}>
                {resetMode ? 'Cancel password reset' : 'Forgot password?'}
              </button>
              {resetMode && (
                <div style={{marginTop:12, padding:12, border:'1px solid #334155', borderRadius:8, background:'#0f172a'}}>
                  <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Username or Email</label>
                  <input className="input" style={{width:'100%', background:'#111827', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8, marginBottom:8}} value={fpUser} onChange={e=>setFpUser(e.target.value)} />
                  <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>Reset Code</label>
                  <input className="input" style={{width:'100%', background:'#111827', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8, marginBottom:8}} value={fpOtp} onChange={e=>setFpOtp(e.target.value.replace(/\D/g,'').slice(0,6))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="6-digit code from your email" />
                  <label style={{display:'block', color:'#94a3b8', fontSize:12, marginBottom:6}}>New Password</label>
                  <input className="input" type="password" style={{width:'100%', background:'#111827', border:'1px solid #334155', color:'#fff', padding:10, borderRadius:8, marginBottom:12}} value={fpNewPwd} onChange={e=>setFpNewPwd(e.target.value)} />
                  {fpMsg && <div style={{background:'#0ea5e9', color:'#0b1224', padding:8, borderRadius:6, fontSize:12, marginBottom:10}}>{fpMsg}</div>}
                  <div className="btn-group" style={{display:'flex', gap:8}}>
                    <button type="button" className="btn btn-sm btn-primary" style={{flex:1}} disabled={fpBusy} onClick={requestReset}>Send reset code</button>
                    <button type="button" className="btn btn-sm btn-success" style={{flex:1}} disabled={fpBusy} onClick={performReset}>Reset password</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
