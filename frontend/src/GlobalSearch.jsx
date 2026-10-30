import React from 'react';

export function GlobalSearch({ setPage, API, apiFetch, AppIcon }) {
  const [query, setQuery] = React.useState('');
  const [results, setResults] = React.useState(null);
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [selectedIndex, setSelectedIndex] = React.useState(-1);
  const ref = React.useRef(null);
  const shortcutLabel = 'Ctrl+K';

  React.useEffect(() => {
    if (query.length < 2) { setResults(null); return; }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await apiFetch(`${API}/api/search/?q=${encodeURIComponent(query)}&limit=10`);
        const d = await r.json();
        setResults(d.results);
        setSelectedIndex(-1);
      } catch {
        setResults({ hosts: [], cves: [], jobs: [] });
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  React.useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Ctrl+K shortcut
  React.useEffect(() => {
    const handler = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); setOpen(true); ref.current?.querySelector('input')?.focus(); } };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Keyboard navigation for search results
  const handleKeyDown = (e) => {
    if (!open || !results) return;
    const allItems = [...(results.hosts || []), ...(results.cves || [])];
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => Math.min(prev + 1, allItems.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Escape') {
      setOpen(false);
      setSelectedIndex(-1);
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      const item = allItems[selectedIndex];
      if (item) navigate(item.type);
    }
  };

  const navigate = (type) => { setPage(type === 'host' ? 'hosts' : type === 'cve' ? 'cve' : 'jobs'); setQuery(''); setResults(null); setOpen(false); };

  return (
    <div ref={ref} className="top-search" role="search">
      <div className="top-search-shell">
        <span className="top-search-icon" aria-hidden="true"><AppIcon name="search" size={17} /></span>
        <input
          className="input top-search-input"
          placeholder="Search hosts, CVEs, jobs... (Ctrl+K)"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onKeyDown={handleKeyDown}
          aria-label="Search hosts, CVEs, and jobs"
          aria-expanded={open}
          aria-controls="search-results"
          aria-activedescendant={selectedIndex >= 0 ? `search-item-${selectedIndex}` : undefined}
        />
        <span className="top-search-shortcut" aria-hidden="true">{shortcutLabel}</span>
      </div>
      {open && results && (
        <div id="search-results" className="top-search-results" role="listbox">
          {loading && <div style={{ padding: 12, color: '#64748b', fontSize: 13 }}>Searching...</div>}
          {!loading && results.hosts?.length === 0 && results.cves?.length === 0 && results.jobs?.length === 0 && (
            <div style={{ padding: 16, color: '#64748b', textAlign: 'center', fontSize: 13 }}>No results for "{query}"</div>
          )}
          {results.hosts?.length > 0 && (
            <div role="group" aria-label="Hosts">
              <div className="top-search-group">Hosts</div>
              {results.hosts.map((h, idx) => (
                <div
                  key={h.id}
                  id={`search-item-${idx}`}
                  role="option"
                  className={`top-search-item ${selectedIndex === idx ? 'selected' : ''}`}
                  onClick={() => navigate('host')}
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate('host'); }}
                  aria-selected={selectedIndex === idx}
                >
                  <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: '50%', background: h.is_online ? '#22c55e' : '#ef4444', boxShadow: `0 0 0 3px ${h.is_online ? 'rgba(34,197,94,0.14)' : 'rgba(239,68,68,0.14)'}`, flex: '0 0 auto', marginTop: 4 }} />
                  <div><div style={{ fontSize: 13, fontWeight: 600 }}>{h.hostname}</div><div style={{ fontSize: 11, color: '#64748b' }}>{h.ip} - {h.os}</div></div>
                </div>
              ))}
            </div>
          )}
          {results.cves?.length > 0 && (
            <div role="group" aria-label="CVEs">
              <div className="top-search-group">CVEs</div>
              {results.cves.map((c, idx) => {
                const itemIdx = (results.hosts?.length || 0) + idx;
                return (
                  <div
                    key={c.id}
                    id={`search-item-${itemIdx}`}
                    role="option"
                    className={`top-search-item ${selectedIndex === itemIdx ? 'selected' : ''}`}
                    onClick={() => navigate('cve')}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') navigate('cve'); }}
                    aria-selected={selectedIndex === itemIdx}
                  >
                    <span className={`badge badge-${c.severity === 'critical' ? 'danger' : c.severity === 'high' ? 'warning' : 'info'}`} style={{ fontSize: 10 }}>{c.severity}</span>
                    <div><div style={{ fontSize: 13, fontWeight: 600 }}>{c.id}</div><div style={{ fontSize: 11, color: '#64748b' }}>{c.description}</div></div>
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
