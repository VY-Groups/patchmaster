import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { API, useInterval, getToken, setToken, clearToken, getLicenseCache, setLicenseCache, getUser, setUser, authHeaders, apiFetch, hasRole, hasPerm, hasFeature, sanitizeDisplayText, websocketUrl } from './appRuntime';
import { ToastContext, useToast, useToastCtx, ToastContainer } from './ToastSystem';
import { BellIcon, AppIcon, CodeIcon } from './AppIcons';
import './App.css';

const TestingPage = React.lazy(() => import('./TestingPage'));
const AnalyticsOpsPage = React.lazy(() => import('./AnalyticsOpsPage'));
const DashboardOpsPage = React.lazy(() => import('./DashboardOpsPage'));
const HostsOpsPage = React.lazy(() => import('./HostsOpsPage'));
const PatchManagerOpsPage = React.lazy(() => import('./PatchManagerOpsPage'));
const CVEOpsPage = React.lazy(() => import('./CVEOpsPage'));
const ReportsOpsPage = React.lazy(() => import('./ReportsOpsPage'));
const MonitoringOpsPage = React.lazy(() => import('./MonitoringOpsPage'));
const OnboardingOpsPage = React.lazy(() => import('./OnboardingOpsPage'));
const SettingsOpsPage = React.lazy(() => import('./SettingsOpsPage'));
const LocalRepoOpsPage = React.lazy(() => import('./LocalRepoOpsPage'));
const MirrorRepoOpsPage = React.lazy(() => import('./MirrorRepoOpsPage'));
const UsersOpsPage = React.lazy(() => import('./UsersOpsPage'));
const LicenseOpsPage = React.lazy(() => import('./LicenseOpsPage'));
const CICDOpsPage = React.lazy(() => import('./CICDOpsPage'));
const BackupManagerPageView = React.lazy(() => import('./BackupManagerPage'));
const ProvisioningPageView = React.lazy(() => import('./ProvisioningPage'));
const NetworkBootPageView = React.lazy(() => import('./NetworkBootPage'));
const PolicyManagerPageView = React.lazy(() => import('./PolicyManagerPage'));
const SLAOpsPage = React.lazy(() => import('./SLAOpsPage'));
const RemediationPageView = React.lazy(() => import('./RemediationPage'));
const MaintenanceWindowsPageView = React.lazy(() => import('./MaintenanceWindowsPage'));
const PatchHooksPageView = React.lazy(() => import('./PatchHooksPage'));
const BulkPatchPageView = React.lazy(() => import('./BulkPatchPage'));
const HostTimelinePageView = React.lazy(() => import('./HostTimelinePage'));
const LiveCommandPageView = React.lazy(() => import('./LiveCommandPage'));
const AgentUpdatePageView = React.lazy(() => import('./AgentUpdatePage'));
const SoftwarePageView = React.lazy(() => import('./SoftwarePage'));
const JobsPageView = React.lazy(() => import('./JobsPage'));
const OpsQueuePageView = React.lazy(() => import('./OpsQueuePage'));
const PluginIntegrationsPageView = React.lazy(() => import('./PluginIntegrationsPage'));
const RingRolloutPageView = React.lazy(() => import('./RingRolloutPage'));
const RestoreDrillPageView = React.lazy(() => import('./RestoreDrillPage'));
const EvidenceViewerPageView = React.lazy(() => import('./EvidenceViewerPage'));
const AddAssetWizardPageView = React.lazy(() => import('./AddAssetWizardPage'));
const RiskViewPageView = React.lazy(() => import('./RiskViewPage'));
const AlertsCenterPageView = React.lazy(() => import('./AlertsCenterPage'));
const AuditPageView = React.lazy(() => import('./AuditPage'));
const NotificationsPageView = React.lazy(() => import('./NotificationsPage'));

import { GlobalSearch as GlobalSearchView } from './GlobalSearch';
import { NotificationCenter as NotificationCenterView } from './NotificationCenter';
import { LoginPage as LoginPageView } from './LoginPage';
import { LicensePopup as LicensePopupView } from './LicensePopup';
import { AnalyticsDashboardPage as AnalyticsDashboardPageView, DashboardPage as DashboardPageView } from './DashboardPage';
import { HostsPage as HostsPageView } from './HostsPage';
import { CompliancePage as CompliancePageView } from './CompliancePage';
import { GroupsPage as GroupsPageView } from './GroupsPage';
import { PatchManagerPage as PatchManagerPageView } from './PatchManagerPage';
import { PatchFabricPage as PatchFabricPageView } from './PatchFabricPage';
import { SnapshotsPage as SnapshotsPageView } from './SnapshotsPage';
import { ComparePackagesPage as ComparePackagesPageView } from './ComparePackagesPage';
import { WsusPage as WsusPageView } from './WsusPage';
import { OfflinePatchPage as OfflinePatchPageView } from './OfflinePatchPage';
import { SchedulesPage as SchedulesPageView } from './SchedulesPage';

/* Global Search with keyboard navigation */
function GlobalSearch({ setPage }) {
  return <GlobalSearchView setPage={setPage} API={API} apiFetch={apiFetch} AppIcon={AppIcon} />;
}
/* --- Notification Center --- */
function NotificationCenter({ setPage, toast }) {
  return <NotificationCenterView setPage={setPage} toast={toast} API={API} apiFetch={apiFetch} getToken={getToken} websocketUrl={websocketUrl} BellIcon={BellIcon} />;
}

function App() {
  const { toasts, add: toast } = useToast();
  const [token, setTokenState] = useState(getToken());
  const [user, setUserState] = useState(getUser());
  const [page, setPage] = useState('dashboard');
  const [health, setHealth] = useState(null);
  const [hosts, setHosts] = useState([]);
  const [jobs, setJobs] = useState([]);
  // Initialize from localStorage cache so nav renders instantly on page load
  const [licenseInfo, setLicenseInfo] = useState(() => getLicenseCache());
  const [licenseLoaded, setLicenseLoaded] = useState(false); // true after first fetch
  const [showLicensePopup, setShowLicensePopup] = useState(false);
  const [showExpiringWarning, setShowExpiringWarning] = useState(true); // Controls expiring soon banner
  const [opsQueueFocusJobId, setOpsQueueFocusJobId] = useState('');
  const [opsQueueFocusSeq, setOpsQueueFocusSeq] = useState(0);
  // Collapsible sidebar state (persisted)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('pm_sidebar_collapsed') === 'true'; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem('pm_sidebar_collapsed', sidebarCollapsed); } catch {}
  }, [sidebarCollapsed]);
  
  // Dark mode state - initialize from localStorage
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('pm_dark_mode');
    return saved === 'true';
  });

  // Apply dark mode to document root
  useEffect(() => {
    if (darkMode) {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('pm_dark_mode', darkMode);
  }, [darkMode]);

  const toggleDarkMode = (e) => {
    const next = !darkMode;
    // Circular reveal theme switch (View Transitions API) with fallback
    const root = document.documentElement;
    if (typeof document.startViewTransition === 'function') {
      const x = e?.clientX ?? window.innerWidth / 2;
      const y = e?.clientY ?? window.innerHeight / 2;
      const endRadius = Math.hypot(
        Math.max(x, window.innerWidth - x),
        Math.max(y, window.innerHeight - y)
      );
      const transition = document.startViewTransition(() => {
        setDarkMode(next);
      });
      transition.ready.then(() => {
        root.animate(
          [
            { clipPath: `circle(0px at ${x}px ${y}px)` },
            { clipPath: `circle(${endRadius}px at ${x}px ${y}px)` },
          ],
          { duration: 400, easing: 'ease-in-out', pseudoElement: '::view-transition-new(root)' }
        );
      }).catch(() => {});
    } else {
      setDarkMode(next);
    }
  };

  const handleLogin = (t, u) => {
    setToken(t); setUser(u); setTokenState(t); setUserState(u);
    // Fetch license immediately after login so features appear right away
    fetch(`${API}/api/license/status`).then(async r => {
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || typeof d.valid !== 'boolean') throw new Error('license status unavailable');
      setLicenseCache(d); setLicenseInfo(d); setLicenseLoaded(true);
      if (!d.valid || !d.activated || d.expired) setPage('license');
    }).catch(() => {
      setLicenseLoaded(true);
      const cached = getLicenseCache();
      if (cached && cached.valid && cached.activated && !cached.expired) {
        setLicenseInfo(cached);
        return;
      }
      setPage('license');
    });
  };
  const handleLogout = () => { clearToken(); setTokenState(null); setUserState(null); setLicenseLoaded(false); localStorage.removeItem('pm_license'); };

  const fetchAll = useCallback(() => {
    if (!getToken()) return;
    fetch(`${API}/api/health`).then(r => r.json()).then(setHealth).catch(() => setHealth(null));
    fetch(`${API}/api/license/status`).then(async r => {
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || typeof d.valid !== 'boolean') throw new Error('license status unavailable');
      setLicenseCache(d);
      setLicenseInfo(d);
      setLicenseLoaded(true);
      if (!d.valid || !d.activated || d.expired) {
        setHosts([]);
        setJobs([]);
        setPage('license');
        return;
      }
      apiFetch(`${API}/api/hosts/`).then(r => r.json()).then(d => { 
        // Handle both array format and paginated format {items: [...]}
        if (Array.isArray(d)) {
          setHosts(d);
        } else if (Array.isArray(d?.items)) {
          setHosts(d.items);
        }
      }).catch(() => {});
      apiFetch(`${API}/api/jobs/`).then(r => r.json()).then(d => { if (Array.isArray(d)) setJobs(d); }).catch(() => {});
    }).catch(() => {
      setLicenseLoaded(true);
      const cached = getLicenseCache();
      if (cached && cached.valid && cached.activated && !cached.expired) {
        setLicenseInfo(cached);
        return;
      }
      setPage('license');
    });
    // Re-fetch user so permissions reflect any license changes without re-login
    apiFetch(`${API}/api/auth/me`).then(r => r.ok ? r.json() : null).then(u => { if (u) { setUser(u); setUserState(u); } }).catch(() => {});
  }, []);

  useEffect(() => { if (token) { fetchAll(); const t = setInterval(fetchAll, 15000); return () => clearInterval(t); } }, [token, fetchAll]);
  useEffect(() => {
    const handler = (event) => {
      const jobId = String(event?.detail?.jobId || '').trim();
      if (!jobId) return;
      setOpsQueueFocusJobId(jobId);
      setOpsQueueFocusSeq((v) => v + 1);
      setPage('ops-queue');
    };
    window.addEventListener('pm-open-ops-queue', handler);
    return () => window.removeEventListener('pm-open-ops-queue', handler);
  }, []);

  // Auto-show license popup only after we've confirmed license status from server
  // (prevents false popup flash on page load before fetch completes)
  useEffect(() => {
    if (licenseLoaded && licenseInfo && (!licenseInfo.valid || !licenseInfo.activated || licenseInfo.expired)) {
      setShowLicensePopup(true);
      setPage('license');
    } else if (licenseLoaded) {
      setShowLicensePopup(false);
    }
  }, [licenseInfo, licenseLoaded]);

  // Show expiring warning when license has 30 days or less remaining
  useEffect(() => {
    if (licenseInfo && licenseInfo.valid && !licenseInfo.expired && licenseInfo.days_remaining <= 30) {
      setShowExpiringWarning(true);
    }
  }, [licenseInfo]);

  if (!token) return <LoginPage onLogin={handleLogin} />;

  const navItems = [
    { key: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
    { key: 'analytics', label: 'Analytics', icon: 'analytics' },
    ...(hasFeature('compliance', licenseInfo) ? [{ key: 'compliance', label: 'Compliance', icon: 'shield' }] : []),
    ...(hasFeature('hosts', licenseInfo) ? [{ key: 'hosts', label: 'Hosts', icon: 'server' }] : []),
    ...(hasFeature('groups', licenseInfo) ? [{ key: 'groups', label: 'Groups & Tags', icon: 'layers' }] : []),
    ...((hasFeature('patches', licenseInfo) || hasFeature('offline', licenseInfo) || hasFeature('local-repo', licenseInfo))
      ? [{ key: 'patch-fabric', label: 'Patch Management', icon: 'layers' }]
      : []),
    ...(hasFeature('compare', licenseInfo) ? [{ key: 'compare', label: 'Compare Packages', icon: 'compare' }] : []),
    ...(hasFeature('schedules', licenseInfo) ? [{ key: 'schedules', label: 'Schedules', icon: 'clock' }] : []),
    ...(hasFeature('cve', licenseInfo) ? [{ key: 'cve', label: 'CVE Tracker', icon: 'bug' }] : []),
    ...(hasFeature('jobs', licenseInfo) ? [{ key: 'jobs', label: 'Job History', icon: 'timeline' }] : []),
    ...(hasFeature('jobs', licenseInfo) ? [{ key: 'ops-queue', label: 'Operations Queue', icon: 'timeline' }] : []),
    ...(hasFeature('jobs', licenseInfo) ? [{ key: 'plugins', label: 'Plugin Integrations', icon: 'pipeline' }] : []),
    ...(hasFeature('audit', licenseInfo) ? [{ key: 'audit', label: 'Audit Trail', icon: 'list' }] : []),
    ...(hasFeature('notifications', licenseInfo) ? [{ key: 'notifications', label: 'Notifications', icon: 'bell' }] : []),
    ...(hasFeature('users', licenseInfo) ? [{ key: 'users', label: 'User Management', icon: 'users' }] : []),
    { key: 'license', label: 'License', icon: 'key' },
    ...((hasFeature('cicd', licenseInfo) || hasFeature('git', licenseInfo) || hasPerm('testing')) ? [{ key: 'cicd', label: 'CI/CD Pipelines', icon: 'pipeline' }] : []),
    ...(hasFeature('software', licenseInfo) ? [{ key: 'software', label: 'Software Manager', icon: 'box' }] : []),
    ...(hasFeature('backups', licenseInfo) ? [{ key: 'backups', label: 'Backup & Recovery', icon: 'database' }] : []),
    ...(hasFeature('backups', licenseInfo) ? [{ key: 'provisioning', label: 'Provisioning Center', icon: 'rocket' }] : []),
    ...(hasFeature('onboarding', licenseInfo) ? [{ key: 'network-boot', label: 'Network Boot', icon: 'server' }] : []),
    ...(hasFeature('backups', licenseInfo) ? [{ key: 'restore-drills', label: 'Restore Drills', icon: 'clock' }] : []),
    ...(hasFeature('policies', licenseInfo) ? [{ key: 'policies', label: 'Config Policies', icon: 'sliders' }] : []),
    ...(hasFeature('policies', licenseInfo) ? [{ key: 'ring-rollout', label: 'Ring Rollout', icon: 'clock' }] : []),
    ...(hasFeature('reports', licenseInfo) ? [{ key: 'reports', label: 'Reports', icon: 'reports' }] : []),
    ...(hasFeature('monitoring', licenseInfo) ? [{ key: 'monitoring', label: 'Monitoring Tools', icon: 'monitor' }] : []),
    ...(hasFeature('monitoring', licenseInfo) ? [{ key: 'alerts-center', label: 'Alerts Center', icon: 'bell' }] : []),
    ...(hasPerm('testing') ? [{ key: 'testing', label: 'Testing Center', icon: 'monitor' }] : []),
    ...(hasFeature('onboarding', licenseInfo) ? [{ key: 'onboarding', label: 'Onboarding', icon: 'users' }] : []),
    ...(hasFeature('settings', licenseInfo) ? [{ key: 'settings', label: 'Settings', icon: 'settings' }] : []),
    { key: 'sla', label: 'SLA Tracking', icon: 'clock' },
    { key: 'remediation', label: 'Remediation', icon: 'shield' },
    { key: 'maintenance', label: 'Maintenance Windows', icon: 'calendar' },
    { key: 'host-timeline', label: 'Host Timeline', icon: 'timeline' },
    { key: 'live-cmd', label: 'Live Commands', icon: 'terminal' },
    { key: 'agent-updates', label: 'Agent Updates', icon: 'refresh' },
  ];
  const effectivePage = (page === 'patch-hooks' || page === 'bulk-patch' || page === 'patch-orchestration') ? 'patch-fabric' : page;
  const currentPageMeta = navItems.find(n => n.key === effectivePage) || navItems[0];

  return (
    <ToastContext.Provider value={toast}>
    {/* Skip to content link for keyboard users */}
    <a href="#main-content" className="skip-link">Skip to main content</a>
    <div className="app-container">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <button className="sidebar-toggle" onClick={() => setSidebarCollapsed(p => !p)} aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={sidebarCollapsed ? 'Expand' : 'Collapse'}>
            {sidebarCollapsed ? '\u25B6' : '\u25C0'}
          </button>
          <h2>
            <span className="brand-badge live-logo">
              <img src="/logo-pm.svg" alt="Patch-SecOps Solution" className="brand-logo" />
            </span>
            {!sidebarCollapsed && 'Patch-SecOps Solution'}
          </h2>
          {!sidebarCollapsed && <span className="sidebar-subtitle">by VYGROUP - Enterprise Patch Management</span>}
        </div>
        {/* Compact account section below branding */}
        <div className="sidebar-account">
          {licenseInfo && !sidebarCollapsed && (
            <div className="license-badge" onClick={()=>setPage('license')} title="License status">
              {licenseInfo.valid && licenseInfo.activated && !licenseInfo.expired ? 'Licensed' : (licenseInfo.expired ? 'Expired' : 'No License')}
            </div>
          )}
          <div className="account-row">
            <span className={`status-dot ${health ? 'online' : 'offline'}`}></span>
            {!sidebarCollapsed && <span className="account-name">{user?.username} <span className="badge badge-info" style={{fontSize:9}}>{user?.role}</span></span>}
            <button className="btn btn-sm btn-danger" onClick={handleLogout} style={{padding:'3px 8px',fontSize:11}} title="Logout">
              {sidebarCollapsed ? 'x' : 'Logout'}
            </button>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navItems.map(n => (
            <button
              key={n.key}
              className={`nav-btn ${page === n.key ? 'active' : ''}`}
              onClick={() => setPage(n.key)}
              aria-current={page === n.key ? 'page' : undefined}
              title={sidebarCollapsed ? n.label : undefined}
            >
              <span className="nav-icon" aria-hidden="true"><AppIcon name={n.icon} size={17} /></span>
              {!sidebarCollapsed && <span className="nav-label">{n.label}</span>}
            </button>
          ))}
        </nav>
      </aside>
      <main id="main-content" className="main-content">
        {/* License expired/not-activated popup modal */}
        {showLicensePopup && <LicensePopup licenseInfo={licenseInfo} onSuccess={() => { setShowLicensePopup(false); fetchAll(); }} />}
        {/* Expiring soon warning banner - manually dismissible */}
        {showExpiringWarning && licenseInfo && licenseInfo.valid && !licenseInfo.expired && licenseInfo.days_remaining <= 30 && (
          <div style={{background:'#ffc107',color:'#000',padding:'8px 20px',textAlign:'center',fontWeight:600,display:'flex',alignItems:'center',justifyContent:'center',gap:20,position:'relative'}}>
            <span style={{cursor:'pointer',flex:1}} onClick={()=>setPage('license')}>
              License expires in {licenseInfo.days_remaining} day{licenseInfo.days_remaining!==1?'s':''} ({licenseInfo.expires_at}). Click here to manage.
            </span>
            <button 
              onClick={(e)=>{e.stopPropagation(); setShowExpiringWarning(false);}} 
              style={{background:'transparent',border:'none',color:'#000',fontSize:20,fontWeight:'bold',cursor:'pointer',padding:'0 8px',lineHeight:1}}
              title="Dismiss warning"
            >
              ×
            </button>
          </div>
        )}
        <header className="top-bar">
          <h1 className="page-title"><span className="page-title-badge" aria-hidden="true"><AppIcon name={currentPageMeta.icon} size={18} /></span>{currentPageMeta.label}</h1>
          <div className="top-bar-search">
            <GlobalSearch setPage={setPage} />
          </div>
          <div className="top-bar-actions" style={{display:'flex',alignItems:'center',gap:10,justifyContent:'flex-end'}}>
            <button 
              className="btn btn-sm" 
              onClick={toggleDarkMode} 
              title={darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"}
              aria-label={darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"}
              style={{padding:'8px 12px'}}
            >
              {darkMode ? 'Dark' : 'Light'}
            </button>
            <NotificationCenter setPage={setPage} toast={toast} />
            <button className="btn btn-sm" onClick={fetchAll} title="Refresh data" aria-label="Refresh data">Refresh</button>
          </div>
        </header>
        <div className="content-area">
          <PageErrorBoundary title="Page render error">
          <React.Suspense fallback={<div className="card" style={{ maxWidth: 520 }}>Loading workspace...</div>}>
            <div key={page} className="page-transition">
            {page === 'dashboard' && <DashboardPage health={health} hosts={hosts} jobs={jobs} setPage={setPage} />}
            {page === 'analytics' && <AnalyticsDashboardPage />}
            {page === 'compliance' && hasPerm('compliance') && <CompliancePage />}
            {page === 'hosts' && hasPerm('hosts') && <HostsPage hosts={hosts} setHosts={setHosts} />}
            {page === 'groups' && hasPerm('groups') && <GroupsPage hosts={hosts} />}
            {page === 'patches' && hasPerm('patches') && <PatchManagerPage hosts={hosts} />}
            {page === 'patch-fabric' && (hasPerm('patches') || hasPerm('offline') || hasPerm('local-repo')) && <PatchFabricPage hosts={hosts} jobs={jobs} toast={toast} />}
            {page === 'wsus' && hasPerm('wsus') && <WsusPage hosts={hosts} />}
            {page === 'snapshots' && hasPerm('snapshots') && <SnapshotsPage hosts={hosts} />}
            {page === 'compare' && hasPerm('compare') && <ComparePackagesPage hosts={hosts} />}
            {page === 'offline' && hasPerm('offline') && <OfflinePatchPage hosts={hosts} />}
            {page === 'local-repo' && hasPerm('local-repo') && <LocalRepoPage />}
            {page === 'mirror-repos' && hasPerm('local-repo') && <MirrorReposPage />}
            {page === 'schedules' && hasPerm('schedules') && <SchedulesPage />}
            {page === 'cve' && hasPerm('cve') && <CVEPage />}
            {page === 'jobs' && hasPerm('jobs') && <JobsPage jobs={jobs} setJobs={setJobs} />}
            {page === 'ops-queue' && hasPerm('jobs') && <OpsQueuePage focusJobId={opsQueueFocusJobId} focusJobSeq={opsQueueFocusSeq} />}
            {page === 'plugins' && hasPerm('jobs') && <PluginIntegrationsPage />}
            {page === 'audit' && hasPerm('audit') && <AuditPage />}
            {page === 'notifications' && hasPerm('notifications') && <NotificationsPage />}
            {page === 'users' && hasPerm('users') && <UsersPage />}
            {page === 'license' && <LicensePage licenseInfo={licenseInfo} onRefresh={fetchAll} />}
            {page === 'cicd' && (hasPerm('cicd') || hasPerm('git') || hasPerm('testing')) && <CICDPage />}
            {page === 'software' && hasPerm('software') && <SoftwarePage hosts={hosts} />}
            {page === 'backups' && hasPerm('backups') && <BackupManagerPage />}
            {page === 'provisioning' && hasPerm('backups') && <ProvisioningPage hosts={hosts} />}
            {page === 'network-boot' && hasPerm('onboarding') && <NetworkBootPage hosts={hosts} />}
            {page === 'restore-drills' && hasPerm('backups') && <RestoreDrillPage />}
            {page === 'policies' && hasPerm('policies') && <PolicyManagerPage />}
            {page === 'ring-rollout' && hasPerm('policies') && <RingRolloutPage />}
            {page === 'evidence' && hasPerm('reports') && <EvidenceViewerPage />}
            {page === 'add-asset' && hasPerm('hosts') && <AddAssetWizardPage />}
            {page === 'risk-view' && hasPerm('reports') && <RiskViewPage />}
            {page === 'reports' && hasPerm('reports') && <ReportsPage />}
            {page === 'monitoring' && (hasPerm('monitoring') || hasFeature('monitoring', licenseInfo)) && <MonitoringToolsPage licenseInfo={licenseInfo} hosts={hosts} />}
            {page === 'alerts-center' && (hasPerm('monitoring') || hasFeature('monitoring', licenseInfo)) && <AlertsCenterPage />}
            {page === 'testing' && hasPerm('testing') && <TestingPage apiBase={API} apiFetch={apiFetch} toast={toast} />}
            {page === 'onboarding' && hasPerm('onboarding') && <OnboardingPage />}
            {page === 'settings' && hasPerm('settings') && <SettingsPage health={health} hosts={hosts} jobs={jobs} />}
            {page === 'sla' && <SLAPage />}
            {page === 'remediation' && <RemediationPage />}
            {page === 'maintenance' && <MaintenanceWindowsPage />}
            {(page === 'patch-orchestration' || page === 'patch-hooks' || page === 'bulk-patch') && <PatchOrchestrationPage hosts={hosts} />}
            {page === 'host-timeline' && <HostTimelinePage hosts={hosts} />}
            {page === 'live-cmd' && hasRole('admin','operator') && <LiveCommandPage hosts={hosts} />}
            {page === 'agent-updates' && <AgentUpdatePage hosts={hosts} />}
          </div>
          </React.Suspense>
          </PageErrorBoundary>
        </div>
      </main>
      <ToastContainer toasts={toasts} />
    </div>
    </ToastContext.Provider>
  );
}

/* --- Login Page --- */
function LoginPage({ onLogin }) {
  return <LoginPageView onLogin={onLogin} API={API} />;
}

/* --- License Expired / Not Activated Popup --- */
function LicensePopup({ licenseInfo, onSuccess }) {
  return <LicensePopupView licenseInfo={licenseInfo} onSuccess={onSuccess} API={API} apiFetch={apiFetch} />;
}

/* --- Dashboard --- */
function AnalyticsDashboardPage() {
  return <AnalyticsDashboardPageView API={API} apiFetch={apiFetch} useInterval={useInterval} AppIcon={AppIcon} AnalyticsOpsPage={AnalyticsOpsPage} />;
}
function DashboardPage({ health, hosts, jobs, setPage }) {
  return <DashboardPageView health={health} hosts={hosts} jobs={jobs} setPage={setPage} API={API} apiFetch={apiFetch} useInterval={useInterval} AppIcon={AppIcon} DashboardOpsPage={DashboardOpsPage} />;
}
/* --- Hosts --- */
function HostsPage({ hosts, setHosts }) {
  return <HostsPageView hosts={hosts} setHosts={setHosts} API={API} apiFetch={apiFetch} hasRole={hasRole} AppIcon={AppIcon} useInterval={useInterval} HostsOpsPage={HostsOpsPage} />;
}
/* --- Compliance --- */
function CompliancePage() {
  return <CompliancePageView API={API} apiFetch={apiFetch} AppIcon={AppIcon} />;
}

/* --- Groups & Tags --- */
function GroupsPage({ hosts }) {
  return <GroupsPageView hosts={hosts} API={API} apiFetch={apiFetch} hasRole={hasRole} />;
}

/* --- Patch Manager --- */
function PatchManagerPage({ hosts }) {
  return <PatchManagerPageView hosts={hosts} API={API} apiFetch={apiFetch} AppIcon={AppIcon} useInterval={useInterval} PatchManagerOpsPage={PatchManagerOpsPage} />;
}

function PatchFabricPage({ hosts, jobs, toast }) {
  return (
    <PatchFabricPageView
      hosts={hosts}
      jobs={jobs}
      toast={toast}
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
      hasPerm={hasPerm}
      AppIcon={AppIcon}
      BulkPatchPage={BulkPatchPage}
      PatchManagerOpsPage={PatchManagerOpsPage}
      LocalRepoOpsPage={LocalRepoOpsPage}
      MirrorRepoOpsPage={MirrorRepoOpsPage}
      SnapshotsPage={SnapshotsPage}
      WsusPage={WsusPage}
      OfflinePatchPage={OfflinePatchPage}
    />
  );
}

/* --- Snapshots --- */
function SnapshotsPage({ hosts }) {
  return <SnapshotsPageView hosts={hosts} API={API} apiFetch={apiFetch} authHeaders={authHeaders} />;
}

/* --- Compare Packages --- */
function ComparePackagesPage({ hosts }) {
  return <ComparePackagesPageView hosts={hosts} API={API} apiFetch={apiFetch} sanitizeDisplayText={sanitizeDisplayText} AppIcon={AppIcon} />;
}

/* --- Windows Update Channel --- */
function WsusPage({ hosts }) {
  return <WsusPageView hosts={hosts} API={API} apiFetch={apiFetch} useInterval={useInterval} hasPerm={hasPerm} />;
}

/* --- Offline Patching --- */
function OfflinePatchPage({ hosts, allowedOS = 'all', channelTitle = 'Offline Patching and Air-Gapped Setup' }) {
  return <OfflinePatchPageView hosts={hosts} allowedOS={allowedOS} channelTitle={channelTitle} API={API} apiFetch={apiFetch} useInterval={useInterval} />;
}


/* --- Schedules --- */
function SchedulesPage() {
  return <SchedulesPageView API={API} apiFetch={apiFetch} />;
}

/* --- CVE Tracker --- */
function CVEPage() {
  return (
    <CVEOpsPage
      API={API}
      apiFetch={apiFetch}
      hasRole={hasRole}
      getToken={getToken}
      AppIcon={AppIcon}
    />
  );
}
/* --- Software Manager --- */
function SoftwarePage({ hosts }) {
  return <SoftwarePageView hosts={hosts} API={API} apiFetch={apiFetch} />;
}

function JobsPage({ jobs, setJobs }) {
  return <JobsPageView jobs={jobs} setJobs={setJobs} API={API} apiFetch={apiFetch} useInterval={useInterval} hasRole={hasRole} />;
}

function OpsQueuePage({ focusJobId, focusJobSeq }) {
  return <OpsQueuePageView API={API} apiFetch={apiFetch} useInterval={useInterval} toast={useToastCtx()} focusJobId={focusJobId} focusJobSeq={focusJobSeq} />;
}

function PluginIntegrationsPage() {
  return <PluginIntegrationsPageView API={API} apiFetch={apiFetch} useInterval={useInterval} toast={useToastCtx()} />;
}

function RingRolloutPage() {
  return <RingRolloutPageView API={API} apiFetch={apiFetch} useInterval={useInterval} toast={useToastCtx()} />;
}

function EvidenceViewerPage() {
  return <EvidenceViewerPageView API={API} apiFetch={apiFetch} />;
}

function AddAssetWizardPage() {
  return <AddAssetWizardPageView API={API} apiFetch={apiFetch} />;
}

function RiskViewPage() {
  return <RiskViewPageView API={API} apiFetch={apiFetch} />;
}

function AuditPage() {
  return <AuditPageView API={API} apiFetch={apiFetch} />;
}

function NotificationsPage() {
  return <NotificationsPageView API={API} apiFetch={apiFetch} hasRole={hasRole} />;
}

function UsersPage() {
  return (
    <UsersOpsPage
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
    />
  );
}

class PageErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, message: String(error?.message || error || 'Unknown error') };
  }
  componentDidCatch() {}
  render() {
    if (this.state.hasError) {
      return (
        <div className="card">
          <h3>{this.props.title || 'Page error'}</h3>
          <p className="text-muted">This page failed to render. Reload or check latest backend migration/restart.</p>
          <pre className="code-block">{this.state.message}</pre>
          <button className="btn btn-primary" onClick={() => this.setState({ hasError: false, message: '' })}>Retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function CICDPage() {
  return (
    <PageErrorBoundary title="CI/CD page error">
      <CICDOpsPage
        API={API}
        apiFetch={apiFetch}
        hasPerm={hasPerm}
        hasRole={hasRole}
        getToken={getToken}
        useToastCtx={useToastCtx}
        TestingPage={TestingPage}
        AppIcon={AppIcon}
      />
    </PageErrorBoundary>
  );
}

function BackupManagerPage() {
  return (
    <BackupManagerPageView
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
    />
  );
}

function ProvisioningPage({ hosts }) {
  return (
    <ProvisioningPageView
      hosts={hosts}
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
    />
  );
}

function NetworkBootPage({ hosts }) {
  return (
    <NetworkBootPageView
      hosts={hosts}
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
      AppIcon={AppIcon}
    />
  );
}

function RestoreDrillPage() {
  return <RestoreDrillPageView API={API} apiFetch={apiFetch} useInterval={useInterval} toast={useToastCtx()} />;
}

function PolicyManagerPage() {
  return (
    <PolicyManagerPageView
      API={API}
      apiFetch={apiFetch}
    />
  );
}

function ReportsPage() {
  return (
    <ReportsOpsPage
      API={API}
      apiFetch={apiFetch}
      getToken={getToken}
      authHeaders={authHeaders}
      toast={useToastCtx()}
      AppIcon={AppIcon}
    />
  );
}
/* --- Local Repository --- */
function LocalRepoPage() {
  return (
    <LocalRepoOpsPage
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
    />
  );
}

function MirrorReposPage() {
  return (
    <MirrorRepoOpsPage
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
    />
  );
}

function MonitoringToolsPage({ licenseInfo, hosts }) {
  return (
    <MonitoringOpsPage
      licenseInfo={licenseInfo}
      hosts={hosts}
      API={API}
      apiFetch={apiFetch}
      hasRole={hasRole}
      getToken={getToken}
    />
  );
}
function AlertsCenterPage() {
  return <AlertsCenterPageView API={API} apiFetch={apiFetch} useInterval={useInterval} toast={useToastCtx()} />;
}
function OnboardingPage() {
  return <OnboardingOpsPage AppIcon={AppIcon} />;
}

function LicensePage({ licenseInfo, onRefresh }) {
  return (
    <LicenseOpsPage
      licenseInfo={licenseInfo}
      onRefresh={onRefresh}
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
    />
  );
}

function SettingsPage({ health, hosts, jobs }) {
  return (
    <SettingsOpsPage
      health={health}
      hosts={hosts}
      jobs={jobs}
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
    />
  );
}

function SLAPage() {
  const toast = useToastCtx();
  return <SLAOpsPage API={API} apiFetch={apiFetch} toast={toast} />;
}

function RemediationPage() {
  const toast = useToastCtx();
  return <RemediationPageView API={API} apiFetch={apiFetch} toast={toast} />;
}

function MaintenanceWindowsPage() {
  const toast = useToastCtx();
  return <MaintenanceWindowsPageView API={API} apiFetch={apiFetch} toast={toast} />;
}

function PatchHooksPage() {
  const toast = useToastCtx();
  return <PatchHooksPageView API={API} apiFetch={apiFetch} toast={toast} />;
}

function BulkPatchPage({ hosts, linuxHosts, windowsHosts }) {
  const toast = useToastCtx();
  return (
    <BulkPatchPageView
      hosts={hosts}
      linuxHosts={linuxHosts || hosts.filter(h => !String(h?.os || '').toLowerCase().includes('windows'))}
      windowsHosts={windowsHosts || hosts.filter(h => String(h?.os || '').toLowerCase().includes('windows'))}
      API={API}
      apiFetch={apiFetch}
      toast={toast}
    />
  );
}

function PatchOrchestrationPage({ hosts }) {
  const toast = useToastCtx();
  const linuxHosts = hosts.filter(h => !String(h?.os || '').toLowerCase().includes('windows'));
  const windowsHosts = hosts.filter(h => String(h?.os || '').toLowerCase().includes('windows'));
  return (
    <BulkPatchPageView
      hosts={hosts}
      linuxHosts={linuxHosts}
      windowsHosts={windowsHosts}
      API={API}
      apiFetch={apiFetch}
      toast={toast}
    />
  );
}

function HostTimelinePage({ hosts }) {
  return <HostTimelinePageView hosts={hosts} API={API} apiFetch={apiFetch} CodeIcon={CodeIcon} />;
}

function LiveCommandPage({ hosts }) {
  return <LiveCommandPageView hosts={hosts} API={API} apiFetch={apiFetch} CodeIcon={CodeIcon} />;
}

function AgentUpdatePage({ hosts }) {
  return <AgentUpdatePageView hosts={hosts} API={API} apiFetch={apiFetch} hasRole={hasRole} CodeIcon={CodeIcon} />;
}

export default App;




