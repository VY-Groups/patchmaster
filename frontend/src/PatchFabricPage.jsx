import React, { useState, useEffect } from 'react';
import { UnifiedPatchHistoryPage } from './UnifiedPatchHistoryPage';
import { PatchRunbookWizard } from './PatchRunbookWizard';

export function PatchFabricPage({ hosts, jobs, toast, API, apiFetch, useInterval, hasPerm, AppIcon, BulkPatchPage, PatchManagerOpsPage, LocalRepoOpsPage, MirrorRepoOpsPage, SnapshotsPage, WsusPage, OfflinePatchPage }) {
  const [activeView, setActiveView] = useState('linux-channel');
  const onlineHosts = hosts.filter(h => h.is_online).length;
  const runningJobs = jobs.filter(j => (j.status || '').toLowerCase() === 'running').length;
  const windowsPatchEnabled = hasPerm('windows_patching') || hasPerm('wsus');
  const windowsHosts = hosts.filter(h => {
    const os = String(h?.os || '').toLowerCase();
    const groups = Array.isArray(h?.groups) ? h.groups.map(g => String(g || '').toLowerCase()) : [];
    return os.includes('windows') || groups.includes('windows');
  });
  const linuxHosts = hosts.filter(h => !windowsHosts.some(w => w.id === h.id));
  useEffect(() => {
    if (activeView === 'windows-channel' && !windowsPatchEnabled) {
      setActiveView('linux-channel');
    }
  }, [activeView, windowsPatchEnabled]);
  return (
    <div>
      <div className="card highlight-card">
        <h3>Patch Management Control Plane</h3>
        <p>Single feature for Linux and Windows patch operations with transparent repository pipeline: online sources to local repository to controlled server push.</p>
      </div>
      <div className="stats-grid" style={{ marginBottom: 12 }}>
        <div className="stat-card"><div className="stat-icon"><AppIcon name="server" size={20} /></div><div className="stat-info"><span className="stat-number">{hosts.length}</span><span className="stat-label">Hosts</span></div></div>
        <div className="stat-card success"><div className="stat-icon"><AppIcon name="monitor" size={20} /></div><div className="stat-info"><span className="stat-number">{onlineHosts}</span><span className="stat-label">Online</span></div></div>
        <div className="stat-card warning"><div className="stat-icon"><AppIcon name="timeline" size={20} /></div><div className="stat-info"><span className="stat-number">{runningJobs}</span><span className="stat-label">Running Jobs</span></div></div>
      </div>
      <div className="card">
        <div className="btn-group" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <button className={`btn btn-sm ${activeView === 'linux-channel' ? 'btn-primary' : ''}`} onClick={() => setActiveView('linux-channel')}><AppIcon name="terminal" size={14} style={{marginRight:4}} /> Linux Channel</button>
          {windowsPatchEnabled && (
            <button className={`btn btn-sm ${activeView === 'windows-channel' ? 'btn-primary' : ''}`} onClick={() => setActiveView('windows-channel')}><AppIcon name="monitor" size={14} style={{marginRight:4}} /> Windows Channel</button>
          )}
          <button className={`btn btn-sm ${activeView === 'orchestration' ? 'btn-primary' : ''}`} onClick={() => setActiveView('orchestration')}><AppIcon name="layers" size={14} style={{marginRight:4}} /> Orchestration</button>
          <button className={`btn btn-sm ${activeView === 'history' ? 'btn-primary' : ''}`} onClick={() => setActiveView('history')}><AppIcon name="timeline" size={14} style={{marginRight:4}} /> Patch History</button>
          <button className={`btn btn-sm ${activeView === 'runbook' ? 'btn-primary' : ''}`} onClick={() => setActiveView('runbook')}><AppIcon name="list" size={14} style={{marginRight:4}} /> Patch Runbook</button>
          <button className={`btn btn-sm ${activeView === 'mirror' ? 'btn-primary' : ''}`} onClick={() => setActiveView('mirror')}><AppIcon name="refresh" size={14} style={{marginRight:4}} /> Repository Mirrors</button>
          <button className={`btn btn-sm ${activeView === 'local-repo' ? 'btn-primary' : ''}`} onClick={() => setActiveView('local-repo')}><AppIcon name="package" size={14} style={{marginRight:4}} /> Local Repository</button>
          <button className={`btn btn-sm ${activeView === 'snapshots' ? 'btn-primary' : ''}`} onClick={() => setActiveView('snapshots')}><AppIcon name="camera" size={14} style={{marginRight:4}} /> Snapshots</button>
        </div>
      </div>
      {activeView === 'history' && <UnifiedPatchHistoryPage hosts={hosts} jobs={jobs} />}
      {activeView === 'runbook' && <PatchRunbookWizard hosts={hosts} />}
      {activeView === 'orchestration' && (
        <BulkPatchPage
          hosts={hosts}
          linuxHosts={linuxHosts}
          windowsHosts={windowsHosts}
          API={API}
          apiFetch={apiFetch}
          toast={toast}
        />
      )}
      {activeView === 'linux-channel' && (
        <div>
          <div className="card"><h3>Linux Patch Operations</h3><p className="text-muted">Linux-only scope. No Windows host appears in this channel.</p></div>
          <PatchManagerOpsPage
            hosts={linuxHosts}
            API={API}
            apiFetch={apiFetch}
            AppIcon={AppIcon}
            useInterval={useInterval}
          />
          <OfflinePatchPage hosts={linuxHosts} allowedOS="linux" channelTitle="Linux Offline Push" />
        </div>
      )}
      {activeView === 'windows-channel' && (
        <div>
          <div className="card"><h3>Windows Patch Operations</h3><p className="text-muted">Dedicated Windows update workflow for Windows hosts with scan, download, install, and controlled offline push support.</p></div>
          <WsusPage hosts={windowsHosts} />
          <OfflinePatchPage hosts={windowsHosts} allowedOS="windows" channelTitle="Windows Offline Push" />
        </div>
      )}
      {activeView === 'mirror' && (
        <MirrorRepoOpsPage
          API={API}
          apiFetch={apiFetch}
          AppIcon={AppIcon}
        />
      )}
      {activeView === 'local-repo' && (
        <LocalRepoOpsPage
          API={API}
          apiFetch={apiFetch}
          AppIcon={AppIcon}
        />
      )}
      {activeView === 'snapshots' && <SnapshotsPage hosts={hosts} />}
    </div>
  );
}
