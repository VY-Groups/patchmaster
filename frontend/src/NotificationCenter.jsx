import React, { useState, useEffect } from 'react';

export function NotificationCenter({ setPage, toast, API, apiFetch, getToken, websocketUrl, BellIcon }) {
  const [notes, setNotes] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);

  const normalizeNotes = (payload) => {
    const items = Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];
    return items.map((n, idx) => ({
      id: n?.id ?? `note-${idx}`,
      type: typeof n?.type === 'string' ? n.type : '',
      title: typeof n?.title === 'string' && n.title.trim() ? n.title : 'Notification',
      message: typeof n?.message === 'string' ? n.message : '',
      link: typeof n?.link === 'string' ? n.link : '',
      is_read: Boolean(n?.is_read),
      created_at: typeof n?.created_at === 'string' ? n.created_at : '',
    }));
  };

  const navigateNotification = (link) => {
    const raw = (link || '').trim();
    if (!raw) return;
    const cleaned = raw.replace(/^#\/?/, '').replace(/^\/+/, '');
    const key = cleaned.split(/[/?#]/)[0];
    const routeMap = {
      dashboard: 'dashboard',
      hosts: 'hosts',
      host: 'hosts',
      cve: 'cve',
      cves: 'cve',
      jobs: 'jobs',
      job: 'jobs',
      notifications: 'notifications',
      reports: 'reports',
      license: 'license',
      monitoring: 'monitoring',
      settings: 'settings',
      onboarding: 'onboarding',
      backups: 'backups',
      software: 'software',
      policies: 'policies',
      users: 'users',
      testing: 'testing',
    };
    if (setPage && routeMap[key]) {
      setPage(routeMap[key]);
      return;
    }
    if (raw.startsWith('http://') || raw.startsWith('https://')) {
      window.open(raw, '_blank', 'noopener,noreferrer');
    }
  };

  const fetchNotes = () => {
    apiFetch(`${API}/api/notifications/me`).then(r=>r.json()).then(d=>{
      const normalized = normalizeNotes(d);
      setNotes(normalized);
      setUnreadCount(normalized.filter(n => !n.is_read).length);
    }).catch(()=>{
      setNotes([]);
      setUnreadCount(0);
    });
  };

  useEffect(() => {
    fetchNotes();
    const interval = setInterval(fetchNotes, 30000);
    let ws;
    const token = getToken();
    if (token) {
      try {
        ws = new WebSocket(websocketUrl('/api/notifications/ws', token));
        ws.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload?.type !== 'snapshot') return;
            const normalized = normalizeNotes(payload);
            setNotes(normalized);
            setUnreadCount(
              typeof payload.unread_count === 'number'
                ? payload.unread_count
                : normalized.filter(n => !n.is_read).length
            );
          } catch {
            // Keep polling fallback if a push payload is malformed.
          }
        };
      } catch {
        // Polling remains the fallback path.
      }
    }
    return () => {
      clearInterval(interval);
      if (ws) ws.close();
    };
  }, []);

  const markRead = async (id, link) => {
    try {
      await apiFetch(`${API}/api/notifications/${id}/read`, {method:'POST'});
    } catch (e) {
      toast?.(`Could not mark notification as read: ${e.message}`, 'warning');
    }
    fetchNotes();
    setIsOpen(false);
    navigateNotification(link);
  };

  const markAllRead = async () => {
    try {
      await apiFetch(`${API}/api/notifications/read-all`, {method:'POST'});
      fetchNotes();
    } catch (e) {
      toast?.(`Could not mark notifications as read: ${e.message}`, 'warning');
    }
  };

  return (
    <div className="notification-center">
      <button
        className="notification-trigger"
        onClick={()=>setIsOpen(!isOpen)}
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ''}`}
        aria-expanded={isOpen}
        aria-haspopup="true"
      >
        <span style={{display:'inline-flex', alignItems:'center', justifyContent:'center', color:'#0f172a'}}><BellIcon size={18} /></span>
        {unreadCount > 0 && (
          <span style={{
            position:'absolute', top:-5, right:-8, background:'red', color:'white',
            borderRadius:'50%', padding:'2px 6px', fontSize:10, fontWeight:'bold'
          }} aria-label={`${unreadCount} unread notifications`}>{unreadCount}</span>
        )}
      </button>

      {isOpen && (
        <div className="notification-panel" role="dialog" aria-label="Notifications panel" aria-modal="false">
          <div className="notification-header">
            <h4 style={{margin:0, fontSize:14}}>Notifications</h4>
            <button className="btn btn-sm btn-link" style={{fontSize:11, padding:0}} onClick={(e)=>{ e.stopPropagation(); markAllRead(); }}>Mark all read</button>
          </div>
          {notes.length === 0 ? <div className="notification-empty">No notifications</div> : (
            <div role="list" aria-label="Notification list">
              {notes.map(n => {
                const timestamp = n.created_at ? new Date(n.created_at) : null;
                const timeLabel = timestamp && !Number.isNaN(timestamp.getTime())
                  ? timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                  : '--:--';
                return (
                  <div key={n.id} role="listitem" className={`notification-item ${n.is_read ? 'is-read' : 'is-unread'}`} onClick={()=>markRead(n.id, n.link)} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') markRead(n.id, n.link); }}>
                    <div style={{display:'flex', justifyContent:'space-between', marginBottom:4}}>
                      <strong style={{fontSize:13, color: n.type.includes('fail') ? '#ef4444' : n.type.includes('success') ? '#16a34a' : 'inherit'}}>
                        {n.title}
                      </strong>
                      <span className="notification-time">{timeLabel}</span>
                    </div>
                    <p className="notification-message">{(n.message || 'No details available.').replace(/\n/g, ' ')}</p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
