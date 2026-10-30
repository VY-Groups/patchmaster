import React, { useState } from 'react';
import './OpsPages.css';

export default function ReportsOpsPage({ API, apiFetch, getToken, authHeaders, toast, AppIcon }) {
  const [downloading, setDownloading] = useState(false);
  const [downloadingType, setDownloadingType] = useState('');

  const downloadPdf = async (type) => {
    setDownloadingType(type);
    try {
      const response = await apiFetch(`${API}/api/reports/download/${type}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload?.error?.message || payload?.detail || `Download failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      const disposition = response.headers.get('content-disposition') || '';
      const parsedName = disposition.includes('filename=')
        ? disposition.split('filename=')[1].replace(/"/g, '').trim()
        : `PatchMaster_${type}_Report.pdf`;
      a.href = url;
      a.download = parsedName;
      a.click();
      window.URL.revokeObjectURL(url);
      if (toast) toast(`${type.replace('_', ' ')} report downloaded`, 'success');
    } catch (e) {
      if (toast) toast(`Report download failed: ${e.message}`, 'danger');
      else alert(`Report download failed: ${e.message}`);
    } finally {
      setDownloadingType('');
    }
  };

  const downloadCsv = async () => {
    setDownloading(true);
    try {
      const r = await apiFetch(`${API}/api/reports/patch-summary.csv`);
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt || `Status ${r.status}`);
      }
      const blob = await r.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'patch_summary.csv';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      alert('Download failed: ' + e.message);
    }
    setDownloading(false);
  };

  const reportCards = [
    {
      title: 'System Hardening Report',
      desc: 'Detailed breakdown of policy compliance, OS versions, and hardening scores across the fleet.',
      action: () => downloadPdf('hardening'),
      button: downloadingType === 'hardening' ? 'Preparing...' : 'Download PDF',
      buttonClass: 'btn btn-primary',
      disabled: !!downloadingType || downloading,
      icon: 'shield',
      color: '#2563eb',
      bg: 'rgba(37,99,235,0.12)',
      audience: 'Security and platform teams',
    },
    {
      title: 'Compliance Executive Summary',
      desc: 'High-level overview of patching status, SLA adherence, and risk exposure for leadership review.',
      action: () => downloadPdf('compliance'),
      button: downloadingType === 'compliance' ? 'Preparing...' : 'Download PDF',
      buttonClass: 'btn btn-primary',
      disabled: !!downloadingType || downloading,
      icon: 'analytics',
      color: '#0f766e',
      bg: 'rgba(16,185,129,0.12)',
      audience: 'Executives and audit stakeholders',
    },
    {
      title: 'Full System Audit',
      desc: 'Complete raw data export of hosts, packages, CVEs, and user activity logs for deep investigation.',
      action: () => downloadPdf('full_system'),
      button: downloadingType === 'full_system' ? 'Preparing...' : 'Download PDF',
      buttonClass: 'btn btn-primary',
      disabled: !!downloadingType || downloading,
      icon: 'database',
      color: '#06b6d4',
      bg: 'rgba(139,92,246,0.12)',
      audience: 'Audit, GRC, and operations',
    },
    {
      title: 'DevOps Delivery Report',
      desc: 'Industry-focused delivery report covering pipelines, builds, deployments, artifacts, and standalone readiness.',
      action: () => downloadPdf('devops'),
      button: downloadingType === 'devops' ? 'Preparing...' : 'Download PDF',
      buttonClass: 'btn btn-primary',
      disabled: !!downloadingType || downloading,
      icon: 'pipeline',
      color: '#1d4ed8',
      bg: 'rgba(29,78,216,0.12)',
      audience: 'DevOps, platform engineering, and release managers',
    },
    {
      title: 'Patch Summary CSV',
      desc: 'Export hostname, IP, OS, compliance, reboot flag, last patch time, and groups for downstream analysis.',
      action: downloadCsv,
      button: downloading ? 'Preparing...' : 'Download CSV',
      buttonClass: 'btn btn-success',
      disabled: downloading,
      icon: 'reports',
      color: '#d97706',
      bg: 'rgba(245,158,11,0.14)',
      audience: 'Operations and BI workflows',
    },
  ];

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#bfdbfe', background: 'linear-gradient(145deg, #eff6ff, #f8fbff)' }}>
          <div className="ops-kicker">Governance reporting</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Export pack</span>
              <span className="ops-emphasis-value" style={{ color: '#1d4ed8' }}>5</span>
              <span className="ops-emphasis-meta">report formats ready for audit, leadership, and operations use</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Professional reporting for audit and compliance workflows</h3>
              <p>Generate polished reports for executive review, detailed audit evidence, and downstream CSV analysis without leaving Patch-SecOps Solution.</p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">PDF reports for audit and leadership</span>
            <span className="ops-chip">CSV export for operations analysis</span>
            <span className="ops-chip">One-click downloads</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Suggested audiences</span>
          <div className="ops-inline-list" style={{ marginTop: 0 }}>
            {['Security', 'Compliance', 'Audit', 'Leadership', 'DevOps'].map(item => (
              <div key={item} className="ops-inline-card">
                <strong>{item}</strong>
                <span>ready-made consumption path</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {reportCards.map(card => (
          <div key={card.title} className="ops-summary-card">
            <div className="ops-summary-head">
              <span className="ops-summary-icon" style={{ color: card.color, background: card.bg }}>
                <AppIcon name={card.icon} size={18} />
              </span>
              <span className="ops-summary-label">{card.title}</span>
            </div>
            <div className="ops-summary-sub" style={{ marginTop: 0 }}>{card.desc}</div>
            <div className="ops-table-meta" style={{ marginTop: 10, marginBottom: 14 }}>{card.audience}</div>
            <button className={card.buttonClass} style={{ width: '100%' }} disabled={card.disabled} onClick={card.action}>{card.button}</button>
          </div>
        ))}
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">How teams typically use these reports</div>
            <p className="ops-subtle">Each export maps cleanly to a different review conversation so your reports feel purposeful, not generic.</p>
          </div>
        </div>
        <div className="ops-list">
          <div className="ops-list-item">
            <div className="ops-list-copy">
              <strong>Hardening report</strong>
              <span>Use for platform standards, policy compliance reviews, and technical remediation planning.</span>
            </div>
            <div className="ops-list-metrics"><span className="ops-chip">Technical deep-dive</span></div>
          </div>
          <div className="ops-list-item">
            <div className="ops-list-copy">
              <strong>Executive summary</strong>
              <span>Use for leadership updates, quarterly risk reviews, and compliance steering meetings.</span>
            </div>
            <div className="ops-list-metrics"><span className="ops-chip">Leadership-ready</span></div>
          </div>
          <div className="ops-list-item">
            <div className="ops-list-copy">
              <strong>Full audit export</strong>
              <span>Use when you need defensible evidence, full record history, or deep incident support material.</span>
            </div>
            <div className="ops-list-metrics"><span className="ops-chip">Evidence-grade</span></div>
          </div>
          <div className="ops-list-item">
            <div className="ops-list-copy">
              <strong>CSV patch summary</strong>
              <span>Use for spreadsheets, BI tools, data pipelines, and team-level action tracking outside the app.</span>
            </div>
            <div className="ops-list-metrics"><span className="ops-chip">Ops workflow</span></div>
          </div>
          <div className="ops-list-item">
            <div className="ops-list-copy">
              <strong>DevOps delivery report</strong>
              <span>Use for market-standard release governance covering CI/CD health, deployment throughput, and execution evidence.</span>
            </div>
            <div className="ops-list-metrics"><span className="ops-chip">DevOps baseline</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

{/* placeholder */}
