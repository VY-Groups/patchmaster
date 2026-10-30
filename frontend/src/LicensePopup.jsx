import React, { useState } from 'react';

export function LicensePopup({ licenseInfo, onSuccess, API, apiFetch }) {
  const [key, setKey] = useState('');
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const li = licenseInfo || {};
  const isInvalid = li.activated && li.valid === false;
  const isExpired = li.activated && li.expired;

  const activate = async () => {
    if (!key.trim()) { setMsg('Please enter a license key'); return; }
    setLoading(true); setMsg('');
    try {
      const r = await apiFetch(`${API}/api/license/activate`, { method:'POST', body: JSON.stringify({ license_key: key.trim() }) });
      const d = await r.json();
      if (r.ok) { setMsg(''); onSuccess(); }
      else { setMsg(d.detail || 'Activation failed'); }
    } catch(e) { setMsg('Error: ' + e.message); }
    setLoading(false);
  };

  const handleKeyDown = (e) => { if (e.key === 'Enter') activate(); };

  return (
    <div style={{
      position:'fixed',top:0,left:0,right:0,bottom:0,
      background:'rgba(0,0,0,0.75)',backdropFilter:'blur(6px)',
      display:'flex',alignItems:'center',justifyContent:'center',
      zIndex:10000,
    }}>
      <div style={{
        background:'#1a1a2e',border:'1px solid #374151',borderRadius:16,
        padding:40,maxWidth:520,width:'90%',textAlign:'center',
        boxShadow:'0 20px 60px rgba(0,0,0,0.5)',
      }}>
        <div style={{fontSize:32,marginBottom:16,fontWeight:800,color:'#cbd5e1'}}>{isExpired ? 'Expired' : isInvalid ? 'Invalid' : 'License'}</div>
        <h2 style={{color:'#f9fafb',marginBottom:8,fontSize:22}}>
          {isExpired ? 'License Expired' : isInvalid ? 'License Invalid' : 'License Required'}
        </h2>
        <p style={{color:'#9ca3af',marginBottom:8,fontSize:14,lineHeight:1.6}}>
          {isExpired
            ? `Your Patch-SecOps Solution license expired on ${li.expires_at}. All services are paused until a valid license is activated.`
            : isInvalid
              ? `The current Patch-SecOps Solution license is invalid${li.error ? `: ${li.error}` : '.'} Please activate a valid license to continue.`
              : 'Patch-SecOps Solution requires a valid license to operate. Please enter your license key to activate all services.'}
        </p>
        {(isExpired || isInvalid) && li.customer && (
          <p style={{color:'#6b7280',fontSize:12,marginBottom:16}}>
            Customer: {li.customer} | Plan: {li.plan_label} | Tier: {li.tier_label}
          </p>
        )}
        <p style={{color:'#d1d5db',fontSize:13,marginBottom:20}}>
          Contact your Patch-SecOps Solution vendor to obtain a new license key.
        </p>
        <div style={{display:'flex',gap:10,marginBottom:12}}>
          <input
            className="input"
            style={{flex:1,fontFamily:'monospace',fontSize:12,padding:'10px 14px',background:'#111827',border:'1px solid #374151',color:'#f9fafb',borderRadius:8}}
            placeholder="PM2-xxxxxxxxx.xxxxxxxx (legacy PM1 also accepted)"
            value={key}
            onChange={e => setKey(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
          />
          <button
            className="btn btn-primary"
            onClick={activate}
            disabled={loading}
            style={{padding:'10px 24px',borderRadius:8,fontWeight:600}}
          >
            {loading ? 'Activating...' : 'Activate'}
          </button>
        </div>
        {msg && <p style={{color:'#dc3545',fontWeight:500,fontSize:13,marginTop:8}}>{msg}</p>}
      </div>
    </div>
  );
}
