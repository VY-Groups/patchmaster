import React, { useEffect, useMemo, useState, useCallback } from 'react';

const statusTabs = ['all', 'pending', 'running', 'success', 'failed', 'rolled_back'];

// Local storage persistence hook for filter state (UI-009: Filter Persistence)
function useFilterPersistence(key) {
  const [savedFilters, setSavedFilters] = useState({});

  useEffect(() => {
    try {
      const saved = localStorage.getItem(`pm-filters-${key}`);
      if (saved) {
        setSavedFilters(JSON.parse(saved));
      }
    } catch {}
  }, [key]);

  const saveFilters = useCallback((filters) => {
    try {
      localStorage.setItem(`pm-filters-${key}`, JSON.stringify(filters));
    } catch {}
  }, [key]);

  return [savedFilters, saveFilters];
}

export default function JobsPage({ jobs, setJobs, API, apiFetch, useInterval, hasRole }) {
  // Persist filters to localStorage (UI-009)
  const [persistedFilters, setPersistedFilters] = useFilterPersistence('jobs');
  
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState(persistedFilters.status || 'all');
  const [selectedJob, setSelectedJob] = useState(null);
  const [jobDetail, setJobDetail] = useState(null);
  const [page, setPage] = useState(1);
  const [perPage] = useState(50);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);

  // Defensive array check
  const safeJobs = Array.isArray(jobs) ? jobs : [];

  const refresh = () => {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(perPage));
    if (statusFilter !== 'all') {
      params.set('status', statusFilter);
    }
    
    apiFetch(`${API}/api/jobs/?${params}`)
      .then((response) => response.json())
      .then((data) => {
        // Backend returns paginated response: {items, total, page, per_page, pages}
        if (data && Array.isArray(data.items)) {
          setJobs(data.items);
          setTotal(data.total || 0);
          setPages(data.pages || 1);
        } else if (Array.isArray(data)) {
          // Fallback for non-paginated response
          setJobs(data);
          setTotal(data.length);
          setPages(1);
        } else {
          console.error('Jobs API returned unexpected data:', data);
          setJobs([]);
          setTotal(0);
          setPages(1);
        }
      })
      .catch((error) => {
        console.error('Failed to fetch jobs:', error);
        setJobs([]);
        setTotal(0);
        setPages(1);
      });
  };

  useEffect(() => {
    refresh();
  }, [page, statusFilter]);

  // Persist filters to localStorage when they change (UI-009: Filter Persistence)
  useEffect(() => {
    setPersistedFilters({ status: statusFilter });
  }, [statusFilter, setPersistedFilters]);

  // Keyboard navigation support (UI-014: Keyboard Nav)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl/Cmd + F focuses search
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-input')?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useInterval(refresh, 8000);

  const deleteJob = (id) => {
    if (!window.confirm('Delete job?')) return;
    apiFetch(`${API}/api/jobs/${id}`, { method: 'DELETE' }).then(refresh);
  };

  const openDetail = async (job) => {
    setSelectedJob(job);
    try {
      const response = await apiFetch(`${API}/api/jobs/${job.id}`);
      setJobDetail(await response.json());
    } catch {
      setJobDetail(job);
    }
  };

  useInterval(async () => {
    if (selectedJob && jobDetail && jobDetail.status === 'running') {
      try {
        const response = await apiFetch(`${API}/api/jobs/${selectedJob.id}`);
        setJobDetail(await response.json());
      } catch {}
    }
  }, selectedJob ? 3000 : null);

  const filtered = useMemo(() => safeJobs.filter((job) => {
    const term = search.toLowerCase();
    const matchSearch = (job.action || '').toLowerCase().includes(term)
      || (job.host_name || '').toLowerCase().includes(term)
      || (job.status || '').toLowerCase().includes(term);
    // Status filter is now applied server-side, so we don't filter here
    return matchSearch;
  }), [safeJobs, search]);

  const counts = useMemo(() => {
    // For counts, we need to fetch all statuses - for now, show total only
    // In a production app, you'd have a separate stats endpoint
    const next = {};
    statusTabs.forEach((status) => {
      next[status] = status === 'all' ? total : 0; // Only 'all' shows accurate count
    });
    return next;
  }, [total]);

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }} role="tablist" aria-label="Filter jobs by status">
        {statusTabs.map((status) => (
          <button 
            key={status} 
            className={`btn btn-sm ${statusFilter === status ? 'btn-primary' : ''}`} 
            onClick={() => setStatusFilter(status)}
            role="tab"
            aria-selected={statusFilter === status}
            aria-controls="jobs-table"
          >
            {status === 'all' ? 'All' : status.charAt(0).toUpperCase() + status.slice(1).replace('_', ' ')}
            {counts[status] > 0 && <span style={{ marginLeft: 6, background: 'rgba(255,255,255,0.2)', borderRadius: 10, padding: '1px 6px', fontSize: 10 }}>{counts[status]}</span>}
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Jobs ({total})</h3>
          <div className="form-row">
            <input className="input search-input" placeholder="Search by host, action, status..." value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search jobs by host, action, or status" />
            <button className="btn btn-sm" onClick={refresh} aria-label="Refresh job list">Refresh</button>
          </div>
        </div>
        {filtered.length === 0 ? (
          // UX-004 FIX: Distinguish between "no data" and "no matches"
          safeJobs.length === 0 ? (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
              <h3 style={{ marginBottom: 8, color: 'var(--text-primary)' }}>No jobs yet</h3>
              <p>Patch jobs will appear here once you start patching hosts.</p>
              <p style={{ fontSize: 13, marginTop: 12 }}>
                Go to <strong>Hosts</strong> → Select a host → Click <strong>Patch</strong> to create your first job.
              </p>
            </div>
          ) : (
            <p className="text-muted">No jobs match the filter.</p>
          )
        ) : (
          <>
            <table className="table">
              <thead><tr><th>ID</th><th>Host</th><th>Action</th><th>Status</th><th>By</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>{filtered.map((job) => (
                <tr key={job.id} style={{ cursor: 'pointer' }} onClick={() => openDetail(job)}>
                  <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>#{job.id}</td>
                  <td><strong>{job.host_name || job.host_id || '--'}</strong>{job.host_ip && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{job.host_ip}</div>}</td>
                  <td>{job.action || job.name}</td>
                  <td>
                    <span className={`badge badge-${job.status === 'success' ? 'success' : job.status === 'running' ? 'warning' : job.status === 'failed' ? 'danger' : job.status === 'rolled_back' ? 'info' : 'info'}`}>
                      {job.status === 'running' ? 'Running ' : ''}{job.status}
                    </span>
                  </td>
                  <td style={{ fontSize: 12 }}>{job.initiated_by || '--'}</td>
                  <td style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{job.created_at ? new Date(job.created_at).toLocaleString() : '--'}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {hasRole('admin', 'operator') && <button className="btn btn-sm btn-danger" onClick={() => deleteJob(job.id)}>Del</button>}
                    {hasRole('admin', 'operator') && ['success', 'failed'].includes(job.status) && (
                      <button
                        className="btn btn-sm btn-warning"
                        style={{ marginLeft: 4 }}
                        onClick={async (event) => {
                          event.stopPropagation();
                          if (!window.confirm(`Roll back job #${job.id}? This will attempt to restore the pre-patch snapshot.`)) return;
                          try {
                            const response = await apiFetch(`${API}/api/jobs/${job.id}/rollback`, { method: 'POST' });
                            const payload = await response.json();
                            if (response.ok) refresh();
                            else alert(payload.detail || 'Rollback failed');
                          } catch (error) {
                            alert(`Error: ${error.message}`);
                          }
                        }}
                      >
                        Rollback
                      </button>
                    )}
                  </td>
                </tr>
              ))}</tbody>
            </table>
            {/* Pagination controls */}
            {pages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, padding: '16px 0', borderTop: '1px solid var(--border-color)' }}>
                <button 
                  className="btn btn-sm" 
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  Previous
                </button>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  Page {page} of {pages} ({total} total jobs)
                </span>
                <button 
                  className="btn btn-sm" 
                  onClick={() => setPage(p => Math.min(pages, p + 1))}
                  disabled={page === pages}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {selectedJob && (
        <div className="modal-overlay" onClick={() => { setSelectedJob(null); setJobDetail(null); }}>
          <div className="modal-card" style={{ maxWidth: 700, maxHeight: '80vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3>Job #{selectedJob.id} - {selectedJob.action}</h3>
              <button className="btn btn-sm" onClick={() => { setSelectedJob(null); setJobDetail(null); }}>Close</button>
            </div>
            {jobDetail ? (
              <div>
                <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(3,1fr)', marginBottom: 16 }}>
                  <div className="stat-card"><div className="stat-info"><span className="stat-number" style={{ fontSize: 14 }}>{jobDetail.host_name || jobDetail.host_id}</span><span className="stat-label">Host</span></div></div>
                  <div className="stat-card"><div className="stat-info"><span className="stat-number" style={{ fontSize: 14 }}><span className={`badge badge-${jobDetail.status === 'success' ? 'success' : jobDetail.status === 'running' ? 'warning' : jobDetail.status === 'failed' ? 'danger' : 'info'}`}>{jobDetail.status}</span></span><span className="stat-label">Status</span></div></div>
                  <div className="stat-card"><div className="stat-info"><span className="stat-number" style={{ fontSize: 14 }}>{jobDetail.initiated_by || '--'}</span><span className="stat-label">Initiated By</span></div></div>
                </div>
                <div style={{ marginBottom: 12, fontSize: 13, color: '#475569' }}>
                  <span>Started: {jobDetail.started_at ? new Date(jobDetail.started_at).toLocaleString() : '--'}</span>
                  <span style={{ marginLeft: 16 }}>Completed: {jobDetail.completed_at ? new Date(jobDetail.completed_at).toLocaleString() : '--'}</span>
                </div>
                {jobDetail.output && (
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Output Log {jobDetail.status === 'running' && <span style={{ color: '#f59e0b' }}>Live</span>}</div>
                    <div style={{ background: 'var(--text-primary)', color: '#a5d6a7', padding: 12, borderRadius: 8, fontFamily: 'monospace', fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto', lineHeight: 1.5 }}>
                      {jobDetail.output}
                    </div>
                  </div>
                )}
                {jobDetail.result && (
                  <details style={{ marginTop: 12 }}>
                    <summary>Final Result JSON</summary>
                    <pre className="code-block" style={{ marginTop: 8 }}>{JSON.stringify(jobDetail.result, null, 2)}</pre>
                  </details>
                )}
              </div>
            ) : <p className="text-muted">Loading...</p>}
          </div>
        </div>
      )}
    </div>
  );
}
