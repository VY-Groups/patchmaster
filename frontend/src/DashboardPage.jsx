import React, { useMemo } from 'react';

function RiskGauge({ score }) {
  const color = score >= 70 ? '#ef4444' : score >= 40 ? '#f59e0b' : '#10b981';
  const label = score >= 70 ? 'High Risk' : score >= 40 ? 'Medium Risk' : 'Low Risk';
  const pct = score / 100;
  // SVG arc gauge
  const r = 54, cx = 64, cy = 64;
  const startAngle = -210, endAngle = 30; // 240 degree sweep
  const toRad = d => (d * Math.PI) / 180;
  const arcX = (a) => cx + r * Math.cos(toRad(a));
  const arcY = (a) => cy + r * Math.sin(toRad(a));
  const fillEnd = startAngle + pct * (endAngle - startAngle);
  const largeArc = (endAngle - startAngle) * pct > 180 ? 1 : 0;
  return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:4}}>
      <svg width="128" height="100" viewBox="0 0 128 100">
        <path d={`M ${arcX(startAngle)} ${arcY(startAngle)} A ${r} ${r} 0 1 1 ${arcX(endAngle)} ${arcY(endAngle)}`}
          fill="none" stroke="var(--border-color)" strokeWidth="10" strokeLinecap="round" />
        {score > 0 && <path d={`M ${arcX(startAngle)} ${arcY(startAngle)} A ${r} ${r} 0 ${largeArc} 1 ${arcX(fillEnd)} ${arcY(fillEnd)}`}
          fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />}
        <text x={cx} y={cy + 8} textAnchor="middle" fontSize="22" fontWeight="700" fill={color}>{score}</text>
        <text x={cx} y={cy + 24} textAnchor="middle" fontSize="10" fill="var(--text-secondary)">/ 100</text>
      </svg>
      <span style={{fontSize:12,fontWeight:600,color}}>{label}</span>
    </div>
  );
}

const MAX_DATA_POINTS = 30;

// Timezone utility for consistent date display
const USER_TIMEZONE = typeof Intl !== 'undefined' 
  ? Intl.DateTimeFormat().resolvedOptions().timeZone 
  : 'UTC';

const formatDateTime = (isoString) => {
  if (!isoString) return 'N/A';
  try {
    return new Date(isoString).toLocaleString(undefined, {
      timeZone: USER_TIMEZONE,
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return 'Invalid'; }
};

// Memoized chart component with data windowing
const PatchVelocityChart = React.memo(function PatchVelocityChart({ data }) {
  if (!data || data.length === 0) return null;
  
  // Window data to max 30 points for performance
  const displayData = data.length > MAX_DATA_POINTS 
    ? data.slice(-MAX_DATA_POINTS) 
    : data;
  
  // Memoize max calculation
  const max = useMemo(() => Math.max(...displayData.map(d => d.jobs), 1), [displayData]);
  
  return (
    <div style={{display:'flex',alignItems:'flex-end',gap:6,height:80,marginTop:8}}>
      {displayData.map((d, i) => (
        <div key={i} style={{flex:1,display:'flex',flexDirection:'column',alignItems:'center',gap:4}}>
          <div style={{
            width:'100%', background:'#4361ee', borderRadius:'4px 4px 0 0',
            height: `${(d.jobs / max) * 64}px`, minHeight: d.jobs > 0 ? 4 : 0,
            transition:'height 0.3s ease',
          }} title={`${d.jobs} jobs`} />
          <span style={{fontSize:9,color:'var(--text-secondary)',whiteSpace:'nowrap'}}>{d.date}</span>
        </div>
      ))}
    </div>
  );
});

export function AnalyticsDashboardPage({ API, apiFetch, useInterval, AppIcon, AnalyticsOpsPage }) {
  return (
    <AnalyticsOpsPage
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
      AppIcon={AppIcon}
      PatchVelocityChart={PatchVelocityChart}
    />
  );
}
export function DashboardPage({ health, hosts, jobs, setPage, API, apiFetch, useInterval, AppIcon, DashboardOpsPage }) {
  return (
    <DashboardOpsPage
      health={health}
      hosts={hosts}
      jobs={jobs}
      setPage={setPage}
      API={API}
      apiFetch={apiFetch}
      useInterval={useInterval}
      AppIcon={AppIcon}
      RiskGauge={RiskGauge}
      PatchVelocityChart={PatchVelocityChart}
    />
  );
}
