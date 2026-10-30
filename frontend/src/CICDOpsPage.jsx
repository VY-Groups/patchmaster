import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

export default function CICDOpsPage({ API, apiFetch, hasPerm, hasRole, getToken, useToastCtx, TestingPage, AppIcon }) {
  const canCICD = hasPerm('cicd');
  const canCICDView = hasPerm('cicd_view');
  const canCICDManage = hasPerm('cicd_manage');
  const canCICDExecute = hasPerm('cicd_execute');
  const canCICDApprove = hasPerm('cicd_approve');
  const canGit = hasPerm('git');
  const canTesting = hasPerm('testing');
  const toast = useToastCtx();
  const [tab, setTab] = useState(canCICD ? 'pipelines' : (canGit ? 'repositories' : (canTesting ? 'testing' : '')));
  const [pipelines, setPipelines] = useState([]);
  const [builds, setBuilds] = useState([]);
  const [progress, setProgress] = useState({ points: [], totals: {} });
  const [stageProgress, setStageProgress] = useState({ stages: [] });
  const [dora, setDora] = useState(null);
  const [templates, setTemplates] = useState({});
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editPipeline, setEditPipeline] = useState(null);
  const [selectedPipeline, setSelectedPipeline] = useState(null);
  const [scriptView, setScriptView] = useState(null);
  const [form, setForm] = useState({ name:'', description:'', tool:'internal', server_url:'', auth_type:'token', auth_user:'', auth_token:'', job_path:'', script_type:'internal_v2', script_content:'', trigger_events:[] });
  const [msg, setMsg] = useState('');
  const [triggerParams, setTriggerParams] = useState('');

  // DevOps extras
  const [variables, setVariables] = useState([]);
  const [varForm, setVarForm] = useState({ key:'', value:'', is_secret:false, status:'active' });
  const [environments, setEnvironments] = useState([]);
  const [envForm, setEnvForm] = useState({ name:'', description:'', webhook_url:'', requires_approval:false, approvers:'', approval_quorum:1, approval_sla_minutes:60, escalation_after_minutes:120, escalation_targets:'', status:'active' });
  const [deployments, setDeployments] = useState([]);
  const [depForm, setDepForm] = useState({ environment:'', build_id:'', notes:'', external_url:'', storage_path:'', status:'pending' });
  const [artifacts, setArtifacts] = useState([]);
  const [releaseArtifacts, setReleaseArtifacts] = useState([]);
  const [logs, setLogs] = useState([]);
  const [buildStages, setBuildStages] = useState([]);
  const [selectedBuild, setSelectedBuild] = useState(null);
  const [evidenceDays, setEvidenceDays] = useState(30);
  const [rbacUsers, setRbacUsers] = useState([]);
  const [rbacSaving, setRbacSaving] = useState(false);

  /* ── Secrets state ── */
  const [secrets, setSecrets] = useState([]);
  const [secretsLoading, setSecretsLoading] = useState(false);
  const [secretForm, setSecretForm] = useState({ name: '', description: '', scope: 'global', pipeline_id: '', value: '' });
  const [secretMsg, setSecretMsg] = useState('');

  /* ── Agent Targets state ── */
  const [agentTargets, setAgentTargets] = useState([]);
  const [agentRuns, setAgentRuns] = useState([]);
  const [agentTargetsLoading, setAgentTargetsLoading] = useState(false);
  const [targetForm, setTargetForm] = useState({ pipeline_id: '', environment_id: '', host_id: '', label: '', run_as: '', working_dir: '', is_active: true });
  const [agentTargetMsg, setAgentTargetMsg] = useState('');
  const [hosts, setHosts] = useState([]);

  /* ── Git Repos state ── */
  const [gitRepos, setGitRepos] = useState([]);
  const [gitLoading, setGitLoading] = useState(false);
  const [showRepoForm, setShowRepoForm] = useState(false);
  const [repoForm, setRepoForm] = useState({ name:'', provider:'gitlab', server_url:'', repo_full_name:'', default_branch:'main', auth_token:'' });
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [repoBranches, setRepoBranches] = useState([]);
  const [repoCommits, setRepoCommits] = useState([]);
  const [repoPulls, setRepoPulls] = useState([]);
  const [repoTags, setRepoTags] = useState([]);
  const [repoTree, setRepoTree] = useState([]);
  const [repoFile, setRepoFile] = useState(null);
  const [repoSubTab, setRepoSubTab] = useState('info');
  const [treePath, setTreePath] = useState('');
  const [discoverResults, setDiscoverResults] = useState(null);
  const [discoverLoading, setDiscoverLoading] = useState(false);

  const fetchPipelines = useCallback(() => {
    setLoading(true);
    apiFetch(`${API}/api/cicd/pipelines`).then(r=>r.json()).then(d=>{setPipelines(Array.isArray(d) ? d : []);setLoading(false);}).catch(()=>setLoading(false));
  }, []);

  const fetchBuilds = useCallback((pipelineId) => {
    const url = pipelineId ? `${API}/api/cicd/builds?pipeline_id=${pipelineId}` : `${API}/api/cicd/builds`;
    apiFetch(url).then(r=>r.json()).then(d => setBuilds(Array.isArray(d) ? d : [])).catch(()=>{});
  }, []);

  const fetchProgress = useCallback((pipelineId) => {
    const url = pipelineId ? `${API}/api/cicd/analytics/progress?pipeline_id=${pipelineId}` : `${API}/api/cicd/analytics/progress`;
    apiFetch(url).then(r=>r.json()).then(d => setProgress(d || { points: [], totals: {} })).catch(()=>setProgress({ points: [], totals: {} }));
  }, []);
  const fetchStageProgress = useCallback((pipelineId) => {
    const url = pipelineId ? `${API}/api/cicd/analytics/stage-progress?pipeline_id=${pipelineId}` : `${API}/api/cicd/analytics/stage-progress`;
    apiFetch(url).then(r=>r.json()).then(d => setStageProgress(d || { stages: [] })).catch(()=>setStageProgress({ stages: [] }));
  }, []);
  const fetchDora = useCallback((pipelineId) => {
    const url = pipelineId ? `${API}/api/cicd/analytics/dora?pipeline_id=${pipelineId}` : `${API}/api/cicd/analytics/dora`;
    apiFetch(url).then(r=>r.json()).then(d => setDora(d || null)).catch(()=>setDora(null));
  }, []);

  const fetchTemplates = useCallback(() => {
    apiFetch(`${API}/api/cicd/templates`).then(r=>r.json()).then(setTemplates).catch(()=>{});
  }, []);
  const fetchRbacUsers = useCallback(() => {
    if (!hasRole('admin')) return;
    apiFetch(`${API}/api/auth/users`).then(r=>r.json()).then(setRbacUsers).catch(()=>setRbacUsers([]));
  }, []);

  const fetchSecrets = useCallback((pipelineId) => {
    setSecretsLoading(true);
    const url = pipelineId ? `${API}/api/cicd/secrets/?pipeline_id=${pipelineId}` : `${API}/api/cicd/secrets/`;
    apiFetch(url).then(r => r.json()).then(d => { setSecrets(Array.isArray(d) ? d : []); setSecretsLoading(false); }).catch(() => setSecretsLoading(false));
  }, [API, apiFetch]);

  const fetchAgentTargets = useCallback((pipelineId) => {
    setAgentTargetsLoading(true);
    const url = pipelineId ? `${API}/api/cicd/agent-targets/?pipeline_id=${pipelineId}` : `${API}/api/cicd/agent-targets/`;
    apiFetch(url).then(r => r.json()).then(d => { setAgentTargets(Array.isArray(d) ? d : []); setAgentTargetsLoading(false); }).catch(() => setAgentTargetsLoading(false));
  }, [API, apiFetch]);

  const fetchAgentRuns = useCallback((buildId) => {
    const url = buildId ? `${API}/api/cicd/agent-targets/runs?build_id=${buildId}` : `${API}/api/cicd/agent-targets/runs`;
    apiFetch(url).then(r => r.json()).then(d => setAgentRuns(Array.isArray(d) ? d : [])).catch(() => {});
  }, [API, apiFetch]);

  const fetchHosts = useCallback(() => {
    apiFetch(`${API}/api/hosts/`).then(r => r.json()).then(d => setHosts(Array.isArray(d) ? d : (Array.isArray(d?.items) ? d.items : []))).catch(() => {});
  }, [API, apiFetch]);

  const fetchVariables = useCallback((pipelineId) => {
    if (!pipelineId) { setVariables([]); return; }
    apiFetch(`${API}/api/cicd/pipelines/${pipelineId}/variables`).then(r=>r.json()).then(setVariables).catch(()=>setVariables([]));
  }, []);

  const fetchEnvironments = useCallback((pipelineId) => {
    if (!pipelineId) { setEnvironments([]); return; }
    apiFetch(`${API}/api/cicd/pipelines/${pipelineId}/environments`).then(r=>r.json()).then(setEnvironments).catch(()=>setEnvironments([]));
  }, []);

  const fetchDeployments = useCallback((pipelineId) => {
    if (!pipelineId) { setDeployments([]); return; }
    apiFetch(`${API}/api/cicd/deployments?pipeline_id=${pipelineId}`).then(r=>r.json()).then(setDeployments).catch(()=>setDeployments([]));
  }, []);

  const fetchArtifacts = useCallback((buildId) => {
    if (!buildId) { setArtifacts([]); return; }
    apiFetch(`${API}/api/cicd/builds/${buildId}/artifacts`).then(r=>r.json()).then(setArtifacts).catch(()=>setArtifacts([]));
  }, []);
  const fetchReleaseArtifacts = useCallback((pipelineId) => {
    const url = pipelineId ? `${API}/api/cicd/release-artifacts?pipeline_id=${pipelineId}` : `${API}/api/cicd/release-artifacts`;
    apiFetch(url).then(r=>r.json()).then(setReleaseArtifacts).catch(()=>setReleaseArtifacts([]));
  }, []);

  const fetchLogs = useCallback((buildId) => {
    if (!buildId) { setLogs([]); return; }
    apiFetch(`${API}/api/cicd/builds/${buildId}/logs`).then(r=>r.json()).then(setLogs).catch(()=>setLogs([]));
  }, []);
  const fetchBuildStages = useCallback((buildId) => {
    if (!buildId) { setBuildStages([]); return; }
    apiFetch(`${API}/api/cicd/builds/${buildId}/stages`).then(r=>r.json()).then(setBuildStages).catch(()=>setBuildStages([]));
  }, []);

  /* ── Git Repos functions ── */
  const fetchGitRepos = useCallback(() => {
    setGitLoading(true);
    apiFetch(`${API}/api/git/repos`).then(r=>r.json()).then(d=>{setGitRepos(Array.isArray(d) ? d : []);setGitLoading(false);}).catch(()=>setGitLoading(false));
  }, []);

  useEffect(() => {
    if (canCICD) { fetchPipelines(); fetchBuilds(); fetchProgress(); fetchStageProgress(); fetchDora(); fetchTemplates(); fetchReleaseArtifacts(); fetchRbacUsers(); fetchSecrets(); fetchAgentTargets(); fetchHosts(); }
    if (canGit) { fetchGitRepos(); }
  }, [canCICD, canGit, fetchPipelines, fetchBuilds, fetchProgress, fetchStageProgress, fetchDora, fetchTemplates, fetchReleaseArtifacts, fetchRbacUsers, fetchGitRepos, fetchSecrets, fetchAgentTargets, fetchHosts]);
  useEffect(() => { if(canCICD && selectedPipeline){ fetchVariables(selectedPipeline); fetchEnvironments(selectedPipeline); fetchDeployments(selectedPipeline); fetchProgress(selectedPipeline); fetchStageProgress(selectedPipeline); fetchDora(selectedPipeline); fetchReleaseArtifacts(selectedPipeline); } }, [canCICD, selectedPipeline, fetchVariables, fetchEnvironments, fetchDeployments, fetchProgress, fetchStageProgress, fetchDora, fetchReleaseArtifacts]);
  useEffect(() => { if(canCICD && selectedBuild){ fetchArtifacts(selectedBuild); fetchLogs(selectedBuild); fetchBuildStages(selectedBuild); } }, [canCICD, selectedBuild, fetchArtifacts, fetchLogs, fetchBuildStages]);

  const saveRepo = async () => {
    setMsg('');
    try {
      const r = await apiFetch(`${API}/api/git/repos`, { method:'POST', body: JSON.stringify(repoForm) });
      if (!r.ok) { const d = await r.json(); setMsg(d.detail || 'Save failed'); return; }
      setMsg('Repository connected!'); setShowRepoForm(false);
      setRepoForm({ name:'', provider:'gitlab', server_url:'', repo_full_name:'', default_branch:'main', auth_token:'' });
      fetchGitRepos();
    } catch { setMsg('Error saving repository'); }
  };

  const deleteRepo = async (id) => { if (!window.confirm('Remove this repository?')) return; await apiFetch(`${API}/api/git/repos/${id}`, { method:'DELETE' }); fetchGitRepos(); setSelectedRepo(null); };

  const testRepoConn = async (id) => { setMsg('Testing...'); const r = await apiFetch(`${API}/api/git/repos/${id}/test`, { method:'POST' }); const d = await r.json(); setMsg(d.ok ? `Success: ${d.message}` : `Failed: ${d.message}`); if (d.ok) fetchGitRepos(); };

  const syncRepo = async (id) => { setMsg('Syncing...'); const r = await apiFetch(`${API}/api/git/repos/${id}/sync`, { method:'POST' }); const d = await r.json(); setMsg(d.ok ? 'Success: Synced!' : `Failed: ${d.message||'Sync failed'}`); fetchGitRepos(); };

  const registerWebhook = async (id) => { setMsg('Registering webhook...'); const r = await apiFetch(`${API}/api/git/repos/${id}/webhook/register`, { method:'POST' }); const d = await r.json(); setMsg(d.ok ? `Success: ${d.message}` : `Failed: ${d.message}`); fetchGitRepos(); };

  const removeWebhook = async (id) => { const r = await apiFetch(`${API}/api/git/repos/${id}/webhook`, { method:'DELETE' }); const d = await r.json(); setMsg(d.ok ? 'Success: Webhook removed' : `Failed: ${d.message}`); fetchGitRepos(); };

  const loadRepoBranches = async (id) => { apiFetch(`${API}/api/git/repos/${id}/branches`).then(r=>r.json()).then(setRepoBranches).catch(()=>setRepoBranches([])); };
  const loadRepoCommits = async (id, branch) => { const q = branch ? `?branch=${branch}` : ''; apiFetch(`${API}/api/git/repos/${id}/commits${q}`).then(r=>r.json()).then(setRepoCommits).catch(()=>setRepoCommits([])); };
  const loadRepoPulls = async (id) => { apiFetch(`${API}/api/git/repos/${id}/pulls`).then(r=>r.json()).then(setRepoPulls).catch(()=>setRepoPulls([])); };
  const loadRepoTags = async (id) => { apiFetch(`${API}/api/git/repos/${id}/tags`).then(r=>r.json()).then(setRepoTags).catch(()=>setRepoTags([])); };
  const loadRepoTree = async (id, path) => { const q = path ? `?path=${encodeURIComponent(path)}` : ''; apiFetch(`${API}/api/git/repos/${id}/tree${q}`).then(r=>r.json()).then(setRepoTree).catch(()=>setRepoTree([])); };
  const loadRepoFile = async (id, path) => { apiFetch(`${API}/api/git/repos/${id}/file?path=${encodeURIComponent(path)}`).then(r=>r.json()).then(setRepoFile).catch(()=>setRepoFile(null)); };

  const openRepoDetail = (repo) => {
    setSelectedRepo(repo); setRepoSubTab('info');
    setRepoBranches([]); setRepoCommits([]); setRepoPulls([]); setRepoTags([]); setRepoTree([]); setRepoFile(null); setTreePath('');
    loadRepoBranches(repo.id); loadRepoCommits(repo.id); loadRepoPulls(repo.id);
  };

  const discoverRepos = async () => {
    setDiscoverLoading(true); setDiscoverResults(null);
    const r = await apiFetch(`${API}/api/git/discover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: repoForm.provider,
        token: repoForm.auth_token,
        server_url: repoForm.server_url || '',
      }),
    }); const d = await r.json();
    setDiscoverResults(Array.isArray(d) ? d : (Array.isArray(d?.repos) ? d.repos : []));
    if (d && typeof d.message === 'string') setMsg(d.message);
    setDiscoverLoading(false);
  };

  const resetForm = () => setForm({ name:'', description:'', tool:'internal', server_url:'', auth_type:'token', auth_user:'', auth_token:'', job_path:'', script_type:'internal_v2', script_content:'', trigger_events:[] });

  const savePipeline = async () => {
    setMsg('');
    // Only include auth_credentials when the user has filled in BOTH fields.
    // On edit, auth_user/auth_token start blank (credentials are never sent back
    // from the server). Sending a partial dict would silently overwrite one field
    // while leaving the other blank, breaking the stored credential pair.
    const hasNewCreds = form.auth_type !== 'none' && form.auth_user.trim() && form.auth_token.trim();
    const payload = {
      name: form.name, description: form.description, tool: form.tool,
      server_url: form.server_url, auth_type: form.auth_type,
      ...(hasNewCreds ? { auth_credentials: { user: form.auth_user, token: form.auth_token } } : {}),
      job_path: form.job_path, script_type: form.script_type,
      script_content: form.script_content, trigger_events: form.trigger_events,
    };
    try {
      const url = editPipeline ? `${API}/api/cicd/pipelines/${editPipeline.id}` : `${API}/api/cicd/pipelines`;
      const method = editPipeline ? 'PUT' : 'POST';
      const r = await apiFetch(url, { method, body: JSON.stringify(payload) });
      if (!r.ok) { const d = await r.json(); setMsg(d.detail || 'Save failed'); return; }
      setMsg('Pipeline saved!');
      setShowForm(false); setEditPipeline(null); resetForm(); fetchPipelines();
    } catch { setMsg('Error saving pipeline'); }
  };

  const deletePipeline = async (id) => {
    if (!window.confirm('Delete this pipeline and all its builds?')) return;
    await apiFetch(`${API}/api/cicd/pipelines/${id}`, { method:'DELETE' });
    fetchPipelines(); fetchBuilds();
  };

  const triggerBuild = async (id) => {
    setMsg('');
    let params = {};
    if (triggerParams.trim()) { try { params = JSON.parse(triggerParams); } catch { setMsg('Invalid JSON parameters'); return; } }
    const r = await apiFetch(`${API}/api/cicd/pipelines/${id}/trigger`, { method:'POST', body: JSON.stringify({ parameters: params }) });
    const d = await r.json();
    if (r.ok) { setMsg(`Build triggered — status: ${d.status}`); fetchBuilds(selectedPipeline); fetchPipelines(); }
    else { setMsg(d.detail || 'Trigger failed'); }
  };

  const testConnection = async (id) => {
    setMsg('Testing...');
    const r = await apiFetch(`${API}/api/cicd/pipelines/${id}/test`, { method:'POST' });
    const d = await r.json();
    setMsg(d.ok ? `Success: ${d.message}` : `Failed: ${d.message}`);
  };

  const toggleStatus = async (p) => {
    const newStatus = p.status === 'active' ? 'paused' : 'active';
    await apiFetch(`${API}/api/cicd/pipelines/${p.id}`, { method:'PUT', body: JSON.stringify({ status: newStatus }) });
    fetchPipelines();
  };

  const saveVariable = async () => {
    if (!selectedPipeline) { setMsg('Select a pipeline first'); return; }
    const body = { ...varForm };
    const r = await apiFetch(`${API}/api/cicd/pipelines/${selectedPipeline}/variables`, { method:'POST', body: JSON.stringify(body) });
    if (r.ok) { setVarForm({ key:'', value:'', is_secret:false, status:'active' }); fetchVariables(selectedPipeline); setMsg('Variable saved'); }
    else { const d = await r.json(); setMsg(d.detail || 'Save failed'); }
  };

  const deleteVariable = async (id) => {
    if (!selectedPipeline) return;
    await apiFetch(`${API}/api/cicd/pipelines/${selectedPipeline}/variables/${id}`, { method:'DELETE' });
    fetchVariables(selectedPipeline);
  };

  const saveEnvironment = async () => {
    if (!selectedPipeline) { setMsg('Select a pipeline first'); return; }
    const body = {
      ...envForm,
      approval_quorum: Math.max(parseInt(envForm.approval_quorum || 1), 1),
      approval_sla_minutes: Math.max(parseInt(envForm.approval_sla_minutes || 60), 1),
      escalation_after_minutes: Math.max(parseInt(envForm.escalation_after_minutes || 120), 1),
      approvers: envForm.approvers ? envForm.approvers.split(',').map(a=>a.trim()).filter(Boolean) : [],
      escalation_targets: envForm.escalation_targets ? envForm.escalation_targets.split(',').map(a=>a.trim()).filter(Boolean) : [],
    };
    const r = await apiFetch(`${API}/api/cicd/pipelines/${selectedPipeline}/environments`, { method:'POST', body: JSON.stringify(body) });
    if (r.ok) { setEnvForm({ name:'', description:'', webhook_url:'', requires_approval:false, approvers:'', approval_quorum:1, approval_sla_minutes:60, escalation_after_minutes:120, escalation_targets:'', status:'active' }); fetchEnvironments(selectedPipeline); setMsg('Environment saved'); }
    else { const d = await r.json(); setMsg(d.detail || 'Save failed'); }
  };

  const deleteEnvironment = async (id) => {
    if (!selectedPipeline) return;
    await apiFetch(`${API}/api/cicd/pipelines/${selectedPipeline}/environments/${id}`, { method:'DELETE' });
    fetchEnvironments(selectedPipeline);
  };

  const createDeployment = async () => {
    if (!selectedPipeline || !depForm.environment) { setMsg('Select pipeline and environment'); return; }
    const body = {
      pipeline_id: selectedPipeline,
      environment: depForm.environment,
      build_id: depForm.build_id?parseInt(depForm.build_id):undefined,
      notes: depForm.notes,
      external_url: depForm.external_url,
      storage_path: depForm.storage_path,
      status: depForm.status || 'pending',
    };
    const r = await apiFetch(`${API}/api/cicd/deployments`, { method:'POST', body: JSON.stringify(body) });
    const d = await r.json();
    if (r.ok) { setDepForm({ environment:'', build_id:'', notes:'', external_url:'', storage_path:'', status:'pending' }); fetchDeployments(selectedPipeline); setMsg('Deployment created'); }
    else { setMsg(d.detail || 'Deployment failed'); }
  };

  const decideDeployment = async (id, action) => {
    const note = window.prompt(`${action === 'approve' ? 'Approval' : 'Rejection'} note (optional):`, '') || '';
    const r = await apiFetch(`${API}/api/cicd/deployments/${id}/${action}`, { method:'POST', body: JSON.stringify({ note }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok) {
      setMsg(`Deployment ${action}d`);
      fetchDeployments(selectedPipeline);
    } else {
      setMsg(d.detail || `${action} failed`);
    }
  };

  const downloadApprovalEvidence = async (kind) => {
    const q = new URLSearchParams({ days: String(evidenceDays || 30) });
    if (selectedPipeline) q.set('pipeline_id', String(selectedPipeline));
    const url = `${API}/api/cicd/approvals/evidence.${kind}?${q.toString()}`;
    const t = getToken();
    const resp = await fetch(url, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}));
      setMsg(d.detail || `Evidence download failed (${resp.status})`);
      return;
    }
    const blob = await resp.blob();
    const link = document.createElement('a');
    const dlUrl = window.URL.createObjectURL(blob);
    const contentDisposition = resp.headers.get('content-disposition') || '';
    const filename = contentDisposition.includes('filename=')
      ? contentDisposition.split('filename=')[1].replace(/"/g, '').trim()
      : `cicd_approval_evidence.${kind}`;
    link.href = dlUrl;
    link.download = filename;
    link.click();
    window.URL.revokeObjectURL(dlUrl);
    setMsg(`Downloaded approval evidence (${kind.toUpperCase()})`);
  };

  const uploadArtifact = async (file) => {
    if (!selectedBuild || !file) { setMsg('Select a build and file'); return; }
    const formData = new FormData();
    formData.append('file', file);
    const t = getToken();
    const r = await fetch(`${API}/api/cicd/builds/${selectedBuild}/artifacts/upload`, { method:'POST', headers: t ? { 'Authorization': `Bearer ${t}` } : {}, body: formData });
    if (r.ok) { setMsg('Artifact uploaded'); fetchArtifacts(selectedBuild); }
    else { setMsg('Upload failed'); }
  };

  const markReleaseArtifact = async (artifact, action) => {
    if (!selectedBuild) return;
    const release_version = window.prompt('Release version:', artifact?.meta?.release_version || 'v1.0.0');
    if (release_version === null) return;
    const release_channel = window.prompt('Release channel:', artifact?.meta?.release_channel || 'stable') || 'stable';
    const environment = action === 'promote' ? (window.prompt('Target environment:', 'production') || 'production') : '';
    const notes = window.prompt('Release notes (optional):', '') || '';
    const endpoint = action === 'promote' ? 'promote' : 'release';
    const r = await apiFetch(`${API}/api/cicd/builds/${selectedBuild}/artifacts/${artifact.id}/${endpoint}`, {
      method:'POST',
      body: JSON.stringify({ release_version, release_channel, environment, notes }),
    });
    if (r.ok) {
      setMsg(`Artifact ${action === 'promote' ? 'promoted' : 'marked release-ready'}`);
      fetchArtifacts(selectedBuild);
      fetchReleaseArtifacts(selectedPipeline);
    } else {
      const d = await r.json().catch(() => ({}));
      setMsg(d.detail || `${action} failed`);
    }
  };

  const approveBuildManualGate = async (buildId) => {
    const note = window.prompt('Approval note (optional):', '') || '';
    const r = await apiFetch(`${API}/api/cicd/builds/${buildId}/manual-gate/approve`, { method:'POST', body: JSON.stringify({ note }) });
    if (r.ok) {
      setMsg('Manual gate approved');
      fetchBuilds(selectedPipeline);
      if (selectedBuild === buildId) fetchBuildStages(buildId);
    } else {
      const d = await r.json().catch(() => ({}));
      setMsg(d.detail || 'Failed to approve manual gate');
    }
  };

  const setUserCicdPerm = (userId, key, value) => {
    setRbacUsers(prev => prev.map(u => {
      if (u.id !== userId) return u;
      const cp = { ...(u.custom_permissions || {}) };
      cp[key] = !!value;
      return { ...u, custom_permissions: cp, effective_permissions: { ...(u.effective_permissions || {}), [key]: !!value, cicd: true } };
    }));
  };

  const saveUserCicdPerms = async (user) => {
    if (!hasRole('admin')) return;
    setRbacSaving(true);
    const current = user.custom_permissions || {};
    const payload = {
      permissions: {
        ...current,
        cicd: true,
        cicd_view: !!current.cicd_view,
        cicd_manage: !!current.cicd_manage,
        cicd_execute: !!current.cicd_execute,
        cicd_approve: !!current.cicd_approve,
      }
    };
    const r = await apiFetch(`${API}/api/auth/users/${user.id}/permissions`, { method:'PUT', body: JSON.stringify(payload) });
    setRbacSaving(false);
    if (r.ok) {
      setMsg(`RBAC updated for ${user.username}`);
      fetchRbacUsers();
    } else {
      const d = await r.json().catch(() => ({}));
      setMsg(d.detail || 'Failed to update RBAC');
    }
  };

  const startEdit = (p) => {
    setForm({
      name: p.name, description: p.description, tool: p.tool,
      server_url: p.server_url, auth_type: p.auth_type,
      auth_user: '', auth_token: '',
      job_path: p.job_path, script_type: p.script_type,
      script_content: p.script_content, trigger_events: p.trigger_events || [],
    });
    setEditPipeline(p); setShowForm(true);
  };

  const _defaultTemplates = {
    shell: '#!/bin/bash\nset -e\necho "Starting deployment..."\n# Add your shell commands here\necho "Done."',
    groovy: 'pipeline {\n  agent any\n  stages {\n    stage(\'Build\') {\n      steps {\n        echo \'Building...\'\n      }\n    }\n    stage(\'Deploy\') {\n      steps {\n        echo \'Deploying...\'\n      }\n    }\n  }\n}',
    internal_v2: JSON.stringify({ stages: [{ name: 'Build', command: 'echo building' }, { name: 'Deploy', command: 'echo deploying' }] }, null, 2),
    yaml: 'stages:\n  - build\n  - deploy\nbuild:\n  script:\n    - echo "Building..."\ndeploy:\n  script:\n    - echo "Deploying..."',
  };

  const loadTemplate = (type) => {
    if (templates[type]?.content) {
      setForm(f => ({ ...f, script_type: type, script_content: templates[type].content }));
    } else if (_defaultTemplates[type]) {
      setForm(f => ({ ...f, script_type: type, script_content: _defaultTemplates[type] }));
    } else {
      setMsg(`No template available for "${type}". Paste your script manually.`);
    }
  };

  const statusBadge = (s) => {
    const map = { success:'badge-success', failed:'badge-danger', running:'badge-info', pending:'badge-warning', pending_approval:'badge-warning', approved:'badge-success', rejected:'badge-danger', aborted:'badge-secondary', completed:'badge-success', rolled_back:'badge-warning', active:'badge-success', paused:'badge-warning', disabled:'badge-danger', info:'badge-info' };
    return <span className={`badge ${map[s]||'badge-secondary'}`}>{s}</span>;
  };

  const triggerEvents = ['patch.success','patch.failed','cve.critical','snapshot.created','schedule.executed','compliance.changed'];
  const tabOptions = [
    ...(canCICD ? [{k:'pipelines',l:'Pipelines'},{k:'builds',l:'Builds'},{k:'vars',l:'Variables'},{k:'envs',l:'Environments'},{k:'deploy',l:'Deployments'},{k:'artifacts',l:'Artifacts'},{k:'logs',l:'Logs'},{k:'scripts',l:'Templates'},{k:'secrets',l:'Secrets'},{k:'agent-targets',l:'Agent Targets'},{k:'rbac',l:'CI/CD RBAC'}] : []),
    ...(canGit ? [{k:'repositories',l:'Git Repositories'}] : []),
    ...(canTesting ? [{k:'testing',l:'QA Testing'}] : []),
  ];
  const pipelinesList = Array.isArray(pipelines) ? pipelines : [];
  const gitReposList = Array.isArray(gitRepos) ? gitRepos : [];
  const buildsList = Array.isArray(builds) ? builds : [];
  const activePipelines = pipelinesList.filter((pipeline) => pipeline.status === 'active').length;
  const connectedRepos = gitReposList.filter((repo) => repo.connection_ok).length;
  const recentRuns = buildsList.filter((build) => ['running', 'pending'].includes(build.status)).length;
  const successfulRuns = buildsList.filter((build) => build.status === 'success').length;
  const operationsSummary = useMemo(() => ([
    { label: 'Pipelines', value: pipelinesList.length, sub: `${activePipelines} active`, icon: 'pipeline', color: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
    { label: 'Build activity', value: buildsList.length, sub: `${recentRuns} running or pending`, icon: 'timeline', color: '#06b6d4', bg: 'rgba(139,92,246,0.12)' },
    { label: 'Git connections', value: gitReposList.length, sub: `${connectedRepos} healthy`, icon: 'layers', color: '#0f766e', bg: 'rgba(16,185,129,0.12)' },
    { label: 'Deploy assets', value: artifacts.length, sub: `${deployments.length} deployments tracked`, icon: 'archive', color: '#d97706', bg: 'rgba(245,158,11,0.14)' },
  ]), [pipelinesList.length, activePipelines, buildsList.length, recentRuns, gitReposList.length, connectedRepos, artifacts.length, deployments.length]);
  const isPositiveMsg = !!msg && !/failed|error|invalid/i.test(msg);

  // Guard: show a friendly message instead of a blank page when the user lacks permissions
  if (!canCICD && !canGit && !canTesting) {
    return (
      <div className="card" style={{maxWidth: 640}}>
        <h3 style={{marginTop:0}}>CI/CD access required</h3>
        <p style={{color:'#6b7280', marginBottom:12}}>
          Your role does not include permissions for CI/CD, Git integrations, or the Testing Center. Please ask an administrator to grant
          the <code>cicd</code>, <code>git</code>, or <code>testing</code> permission.
        </p>
      </div>
    );
  }

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#93c5fd', background: 'linear-gradient(145deg, #eff6ff, #f8fbff)' }}>
          <div className="ops-kicker">DevOps and release engineering</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Automation surface</span>
              <span className="ops-emphasis-value" style={{ color: '#1d4ed8' }}>{tabOptions.length}</span>
              <span className="ops-emphasis-meta">Workspaces available across pipelines, repositories, deployments, artifacts, logs, and QA testing.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Give operators one command center for pipelines, repositories, and release evidence.</h3>
              <p>
                This DevOps page now reads like a professional engineering workspace: high-level operational context first, then the full underlying tools for CI/CD orchestration, Git integration, deployment records, artifacts, logs, and QA testing.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">{pipelinesList.length} pipelines</span>
            <span className="ops-chip">{gitReposList.length} repositories</span>
            <span className="ops-chip">{successfulRuns} successful builds</span>
            <span className="ops-chip">{deployments.length} deployments</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Current focus</span>
          <div className="ops-side-metric">{tab === 'testing' ? 'QA' : tab === 'repositories' ? 'Git' : 'CI/CD'}</div>
          <p className="ops-side-note">
            Use the workspace switcher below to move between pipeline administration, repository integration, deployment operations, and testing without losing context.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
              <strong>{activePipelines}</strong>
              <span>active pipelines</span>
            </div>
            <div className="ops-inline-card">
              <strong>{connectedRepos}</strong>
              <span>connected repos</span>
            </div>
            <div className="ops-inline-card">
              <strong>{recentRuns}</strong>
              <span>active build runs</span>
            </div>
            <div className="ops-inline-card">
              <strong>{artifacts.length}</strong>
              <span>loaded artifacts</span>
            </div>
          </div>
        </div>
      </div>

      <div className="ops-summary-grid">
        {operationsSummary.map((card) => (
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
            <p className="ops-subtle">Jump directly into pipeline administration, Git repositories, deployment controls, artifacts, logs, or QA testing.</p>
          </div>
        </div>
        <div className="ops-pills">
          {tabOptions.map(t => (
            <button key={t.k} className={`ops-pill ${tab===t.k?'active':''}`} onClick={()=>{setTab(t.k);if(t.k==='builds')fetchBuilds(selectedPipeline);if(t.k==='repositories')fetchGitRepos();if((t.k==='artifacts'||t.k==='logs') && selectedBuild){fetchArtifacts(selectedBuild);fetchLogs(selectedBuild);} }}>{t.l}</button>
          ))}
        </div>
      </div>
      {canGit ? (
        <div
          className="ops-command-card"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}
        >
          <div>
            <strong>Git server integration lives in the Git Repositories workspace.</strong>
            <div className="ops-subtle" style={{ marginTop: 4 }}>
              Connect GitLab, GitBucket, or Bitbucket servers, browse repositories, sync branches and commits, and register webhooks from one place.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-sm btn-secondary" onClick={() => { setTab('repositories'); fetchGitRepos(); }}>
              Open Git Repositories
            </button>
            <button className="btn btn-sm btn-primary" onClick={() => { setTab('repositories'); fetchGitRepos(); setShowRepoForm(true); }}>
              {gitReposList.length ? 'Connect Another Repository' : 'Connect Git Server'}
            </button>
          </div>
        </div>
      ) : canCICD ? (
        <div className="ops-command-card" style={{ padding: '10px 16px' }}>
          <strong>Git repository integration is available in CI/CD, but this role does not currently expose it.</strong>
          <div className="ops-subtle" style={{ marginTop: 4 }}>
            Ask an administrator to grant the <code>git</code> permission if you need server or repository connections here.
          </div>
        </div>
      ) : null}
      {msg && <div className="ops-command-card" style={{padding:'8px 16px',borderColor:isPositiveMsg?'#86efac':'#fecaca',background:isPositiveMsg?'linear-gradient(145deg, #ecfdf3, #f8fffb)':'linear-gradient(145deg, #fff7ed, #fffdf8)',fontWeight:500}}>{msg}</div>}

      {tab === 'testing' && canTesting && (
        <TestingPage apiBase={API} apiFetch={apiFetch} toast={toast} />
      )}

      {/* ── Pipelines Tab ── */}
      {tab === 'pipelines' && canCICD && canCICDView && (
        <div>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <h3 style={{margin:0}}>CI/CD Pipelines</h3>
            <div style={{display:'flex',gap:8}}>
              <button className="btn btn-sm" onClick={()=>{fetchPipelines(); fetchBuilds(selectedPipeline);}}>Refresh</button>
              {canCICDManage && <button className="btn btn-primary" onClick={()=>{resetForm();setEditPipeline(null);setShowForm(!showForm);}}>
                {showForm ? 'Cancel' : '+ New Pipeline'}
              </button>}
            </div>
          </div>

          {/* Create/Edit form */}
          {showForm && (
            <div className="card" style={{marginBottom:16,border:'2px solid #3b82f6'}}>
              <h4 style={{marginTop:0}}>{editPipeline ? 'Edit Pipeline' : 'Create Pipeline'}</h4>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
                <div>
                  <label style={{fontSize:12,fontWeight:600}}>Pipeline Name *</label>
                  <input className="input" placeholder="e.g. Production Patch Pipeline" value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} />
                </div>
                <div>
                  <label style={{fontSize:12,fontWeight:600}}>CI/CD Tool *</label>
                  <select className="input" value={form.tool} onChange={e=>setForm(f=>({...f,tool:e.target.value,script_type:(e.target.value==='internal'?'internal_v2':(f.script_type==='internal_v2'?'groovy':f.script_type))}))}>
                    <option value="internal">Patch-SecOps Solution Internal (Standalone)</option>
                    <option value="jenkins">Jenkins</option>
                    <option value="gitlab">GitLab CI</option>
                    <option value="custom">Custom Webhook</option>
                  </select>
                </div>
                <div style={{gridColumn:'1/-1',fontSize:12,color:'#64748b'}}>
                  Standalone mode runs fully inside Patch-SecOps Solution. Jenkins/GitLab/Custom remain optional integrations.
                </div>
                <div style={{gridColumn:'1/-1'}}>
                  <label style={{fontSize:12,fontWeight:600}}>Description</label>
                  <input className="input" placeholder="Pipeline description" value={form.description} onChange={e=>setForm(f=>({...f,description:e.target.value}))} />
                </div>
                {form.tool !== 'internal' && (
                  <>
                    <div>
                      <label style={{fontSize:12,fontWeight:600}}>{form.tool === 'jenkins' ? 'Jenkins Server URL *' : 'Server / Webhook URL *'}</label>
                      <input className="input" placeholder={form.tool==='jenkins'?'http://jenkins.example.com:8080':'https://...'} value={form.server_url} onChange={e=>setForm(f=>({...f,server_url:e.target.value}))} />
                    </div>
                    <div>
                      <label style={{fontSize:12,fontWeight:600}}>{form.tool === 'jenkins' ? 'Job Path *' : 'Project / Repo Path'}</label>
                      <input className="input" placeholder={form.tool==='jenkins'?'my-folder/my-job':'owner/repo'} value={form.job_path} onChange={e=>setForm(f=>({...f,job_path:e.target.value}))} />
                    </div>
                    <div>
                      <label style={{fontSize:12,fontWeight:600}}>Auth Type</label>
                      <select className="input" value={form.auth_type} onChange={e=>setForm(f=>({...f,auth_type:e.target.value}))}>
                        <option value="token">API Token</option>
                        <option value="basic">Basic Auth</option>
                        <option value="none">None</option>
                      </select>
                    </div>
                    {form.auth_type !== 'none' && (<>
                      <div>
                        <label style={{fontSize:12,fontWeight:600}}>Username</label>
                        <input className="input" placeholder="Username" value={form.auth_user} onChange={e=>setForm(f=>({...f,auth_user:e.target.value}))} />
                      </div>
                      <div>
                        <label style={{fontSize:12,fontWeight:600}}>{form.auth_type==='token'?'API Token':'Password'}</label>
                        <input className="input" type="password" placeholder="Token / Password" value={form.auth_token} onChange={e=>setForm(f=>({...f,auth_token:e.target.value}))} />
                      </div>
                    </>)}
                  </>
                )}
              </div>

              {/* Script editor */}
              <div style={{marginTop:16}}>
                <div style={{display:'flex',alignItems:'center',gap:12,marginBottom:8}}>
                  <label style={{fontSize:12,fontWeight:600,margin:0}}>Pipeline Script</label>
                  <select className="input" value={form.script_type} onChange={e=>setForm(f=>({...f,script_type:e.target.value}))} style={{width:140}}>
                    <option value="internal_v2">Internal v2 (JSON)</option>
                    <option value="groovy">Groovy (Jenkinsfile)</option>
                    <option value="yaml">YAML</option>
                    <option value="shell">Shell</option>
                  </select>
                  <button className="btn btn-sm btn-secondary" onClick={()=>loadTemplate(form.script_type)}>Load Template</button>
                </div>
                <textarea className="input" style={{width:'100%',minHeight:220,fontFamily:'monospace',fontSize:12,whiteSpace:'pre',overflowWrap:'normal',overflowX:'auto'}}
                  value={form.script_content} onChange={e=>setForm(f=>({...f,script_content:e.target.value}))}
                  placeholder={`Paste your ${form.script_type} pipeline script here...`} />
              </div>

              {/* Trigger events */}
              <div style={{marginTop:12}}>
                <label style={{fontSize:12,fontWeight:600}}>Auto-Trigger on Events</label>
                <div style={{display:'flex',flexWrap:'wrap',gap:8,marginTop:4}}>
                  {triggerEvents.map(ev => (
                    <label key={ev} style={{display:'flex',alignItems:'center',gap:4,fontSize:12,cursor:'pointer'}}>
                      <input type="checkbox" checked={form.trigger_events.includes(ev)}
                        onChange={e => setForm(f => ({...f, trigger_events: e.target.checked ? [...f.trigger_events, ev] : f.trigger_events.filter(x=>x!==ev)}))} />
                      {ev}
                    </label>
                  ))}
                </div>
              </div>

              <div style={{marginTop:16,display:'flex',gap:8}}>
                <button className="btn btn-primary" onClick={savePipeline}>Save Pipeline</button>
                <button className="btn btn-secondary" onClick={()=>{setShowForm(false);setEditPipeline(null);resetForm();}}>Cancel</button>
              </div>
            </div>
          )}

          {/* Pipeline list */}
          {loading ? <p>Loading...</p> : pipelines.length === 0 ? (
            <div className="card" style={{textAlign:'center',padding:40,color:'#9ca3af'}}>
              <p style={{margin:0,display:'inline-flex',alignItems:'center',justifyContent:'center'}}><AppIcon name="pipeline" size={36} /></p>
              <p style={{fontWeight:600}}>No CI/CD Pipelines configured yet</p>
              <p>Create a native pipeline for standalone DevOps workflows, or connect external Jenkins/GitLab/custom webhooks when needed.</p>
            </div>
          ) : (
            <div style={{display:'grid',gap:12}}>
              {pipelines.map(p => (
                <div key={p.id} className="card" style={{border: p.status==='active' ? '1px solid rgba(40,167,69,0.3)' : '1px solid rgba(108,117,125,0.3)'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
                    <div>
                      <div style={{display:'flex',alignItems:'center',gap:10}}>
                        <span style={{display:'inline-flex',color:'#64748b'}}><AppIcon name={p.tool==='jenkins' ? 'settings' : p.tool==='gitlab' ? 'pipeline' : p.tool==='internal' ? 'server' : 'monitor'} size={20} /></span>
                        <div>
                          <h4 style={{margin:0}}>{p.name}</h4>
                          <span style={{fontSize:12,color:'#9ca3af'}}>{p.tool.charAt(0).toUpperCase()+p.tool.slice(1)} • {p.server_url || 'Patch-SecOps Solution internal engine'} • {p.job_path || 'No job path'}</span>
                        </div>
                      </div>
                      {p.description && <p style={{margin:'6px 0 0',fontSize:13,color:'#9ca3af'}}>{p.description}</p>}
                    </div>
                    <div style={{display:'flex',gap:6,alignItems:'center'}}>
                      {statusBadge(p.status)}
                      <span className="badge badge-info" style={{fontSize:10}}>{p.build_count} builds</span>
                      {p.last_build_status && statusBadge(p.last_build_status)}
                    </div>
                  </div>

                  {/* Webhook URL */}
                  <div style={{marginTop:10,padding:8,borderRadius:6,background:'rgba(59,130,246,0.08)',fontSize:12}}>
                    <strong>Webhook URL:</strong> <code style={{wordBreak:'break-all'}}>{p.webhook_url}</code>
                  </div>

                  {/* Trigger events */}
                  {p.trigger_events && p.trigger_events.length > 0 && (
                    <div style={{marginTop:8,fontSize:12}}>
                      <strong>Auto-triggers:</strong> {p.trigger_events.map(e=><span key={e} className="badge badge-info" style={{fontSize:10,marginLeft:4}}>{e}</span>)}
                    </div>
                  )}

                  {/* Actions */}
                  <div style={{marginTop:12,display:'flex',gap:6,flexWrap:'wrap'}}>
                    {canCICDExecute && p.status === 'active' && (
                      <button className="btn btn-sm btn-primary" onClick={()=>triggerBuild(p.id)}>Trigger Build</button>
                    )}
                    <button className="btn btn-sm btn-secondary" onClick={()=>testConnection(p.id)}>Test Connection</button>
                    <button className="btn btn-sm btn-secondary" onClick={()=>{setSelectedPipeline(p.id);setTab('builds');fetchBuilds(p.id);}}>Builds</button>
                    <button className="btn btn-sm btn-secondary" onClick={()=>setScriptView(scriptView===p.id?null:p.id)}>{scriptView===p.id?'Hide':'View'} Script</button>
                    {canCICDManage && <button className="btn btn-sm btn-warning" onClick={()=>startEdit(p)}>Edit</button>}
                    {canCICDManage && <button className="btn btn-sm btn-secondary" onClick={()=>toggleStatus(p)}>{p.status==='active'?'Pause':'Resume'}</button>}
                    {canCICDManage && hasRole('admin') && <button className="btn btn-sm btn-danger" onClick={()=>deletePipeline(p.id)}>Delete</button>}
                  </div>

                  {/* Trigger parameters (inline) */}
                  {canCICDExecute && p.status === 'active' && (
                    <div style={{marginTop:8}}>
                      <input className="input" style={{fontSize:12,width:300}} placeholder='Trigger params JSON e.g. {"branch":"main"}' value={triggerParams} onChange={e=>setTriggerParams(e.target.value)} />
                    </div>
                  )}

                  {/* Script viewer */}
                  {scriptView === p.id && (
                    <div style={{marginTop:10}}>
                      <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                        <span className="badge badge-info">{p.script_type}</span>
                        <span style={{fontSize:12,color:'#9ca3af'}}>Pipeline Script</span>
                      </div>
                      <pre className="code-block" style={{maxHeight:400,overflow:'auto',fontSize:11}}>{p.script_content || '(no script)'}</pre>
                    </div>
                  )}

                  {p.last_triggered && <div style={{marginTop:8,fontSize:11,color:'#9ca3af'}}>Last triggered: {new Date(p.last_triggered).toLocaleString()}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Builds Tab ── */}
      {tab === 'builds' && canCICD && (
        <div>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <h3 style={{margin:0}}>Build History</h3>
            <div style={{display:'flex',gap:8,alignItems:'center'}}>
              <select className="input" style={{width:200}} value={selectedPipeline||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedPipeline(v);fetchBuilds(v);}}>
                <option value="">All Pipelines</option>
                {pipelines.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <button className="btn btn-sm" onClick={()=>{fetchBuilds(selectedPipeline);fetchProgress(selectedPipeline);fetchStageProgress(selectedPipeline);fetchDora(selectedPipeline);}}>Refresh</button>
            </div>
          </div>
          <div className="stats-grid" style={{marginBottom:16}}>
            <div className="stat-card"><div className="stat-info"><span className="stat-number">{dora?.deployment_frequency_per_day ?? 0}</span><span className="stat-label">Deploy/day</span></div></div>
            <div className="stat-card warning"><div className="stat-info"><span className="stat-number">{dora?.change_failure_rate_pct ?? 0}%</span><span className="stat-label">Change Failure Rate</span></div></div>
            <div className="stat-card info"><div className="stat-info"><span className="stat-number">{dora?.lead_time_seconds_avg ?? 0}s</span><span className="stat-label">Lead Time</span></div></div>
            <div className="stat-card success"><div className="stat-info"><span className="stat-number">{dora?.mttr_seconds_avg ?? 0}s</span><span className="stat-label">MTTR</span></div></div>
          </div>
          <div className="card" style={{marginBottom:16}}>
            <h4 style={{marginTop:0}}>Build Progress Graph (Last {progress?.days || 14} days)</h4>
            {(progress?.points || []).length === 0 ? (
              <p style={{color:'#9ca3af',margin:0}}>No build activity yet.</p>
            ) : (
              <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(130px,1fr))',gap:8}}>
                {(progress.points || []).map((pt) => {
                  const total = Math.max(Number(pt.total || 0), 1);
                  const successPct = Math.round((Number(pt.success || 0) / total) * 100);
                  const failedPct = Math.round((Number(pt.failed || 0) / total) * 100);
                  return (
                    <div key={pt.day} style={{border:'1px solid #e5e7eb',borderRadius:8,padding:8}}>
                      <div style={{fontSize:12,color:'#64748b'}}>{pt.day}</div>
                      <div style={{display:'flex',height:10,margin:'6px 0',borderRadius:6,overflow:'hidden',background:'#f1f5f9'}}>
                        <div style={{width:`${successPct}%`,background:'#10b981'}} />
                        <div style={{width:`${failedPct}%`,background:'#ef4444'}} />
                      </div>
                      <div style={{fontSize:12}}>Total {pt.total} · S {pt.success} · F {pt.failed}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="card" style={{marginBottom:16}}>
            <h4 style={{marginTop:0}}>Stage-Level Run Graph</h4>
            {(stageProgress?.stages || []).length === 0 ? (
              <p style={{color:'#9ca3af',margin:0}}>No stage telemetry yet.</p>
            ) : (
              <table className="table">
                <thead><tr><th>Stage</th><th>Total</th><th>Success</th><th>Failed</th><th>Running</th><th>Pending</th></tr></thead>
                <tbody>
                  {(stageProgress.stages || []).map((s) => (
                    <tr key={s.stage_name}>
                      <td>{s.stage_name}</td>
                      <td>{s.total}</td>
                      <td>{s.success}</td>
                      <td>{s.failed}</td>
                      <td>{s.running}</td>
                      <td>{s.pending}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {builds.length === 0 ? (
            <div className="card" style={{textAlign:'center',padding:30,color:'#9ca3af'}}>
              <p>No builds yet. Trigger a pipeline or wait for webhook callbacks.</p>
            </div>
          ) : (
            <table className="table">
              <thead><tr><th>#</th><th>Pipeline</th><th>Status</th><th>Trigger</th><th>Duration</th><th>Started</th><th>Actions</th></tr></thead>
              <tbody>
                {builds.map(b => (
                  <tr key={b.id}>
                    <td><strong>#{b.build_number}</strong></td>
                    <td>{b.pipeline_name}</td>
                    <td>{statusBadge(b.status)}</td>
                    <td><span className="badge badge-secondary" style={{fontSize:10}}>{b.trigger_type}</span></td>
                    <td>{b.duration_seconds ? `${b.duration_seconds}s` : '—'}</td>
                    <td style={{fontSize:12}}>{b.started_at ? new Date(b.started_at).toLocaleString() : '—'}</td>
                    <td style={{display:'flex',gap:4}}>
                      {b.external_url && <a href={b.external_url} target="_blank" rel="noopener noreferrer" className="btn btn-sm btn-info">Open ↗</a>}
                      {b.output && <button className="btn btn-sm btn-secondary" title={b.output} onClick={()=>alert(b.output)}>Log</button>}
                      <button className="btn btn-sm btn-secondary" onClick={()=>{setSelectedBuild(b.id);fetchBuildStages(b.id);}}>Stages</button>
                      {canCICDApprove && String(b.status || '').toLowerCase() === 'pending_approval' && <button className="btn btn-sm btn-success" onClick={()=>approveBuildManualGate(b.id)}>Approve Gate</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {selectedBuild && (
            <div className="card" style={{marginTop:12}}>
              <h4 style={{marginTop:0}}>Build #{builds.find(b => b.id === selectedBuild)?.build_number || selectedBuild} Stages</h4>
              {buildStages.length === 0 ? (
                <p style={{color:'#9ca3af'}}>No stages recorded for this build.</p>
              ) : (
                <table className="table">
                  <thead><tr><th>Stage</th><th>Order</th><th>Status</th><th>Duration</th><th>Started</th><th>Action</th></tr></thead>
                  <tbody>
                    {buildStages.map((s) => (
                      <tr key={s.id}>
                        <td>{s.stage_name}</td>
                        <td>{s.order_index}</td>
                        <td>{statusBadge(s.status)}</td>
                        <td>{s.duration_seconds ? `${s.duration_seconds}s` : '—'}</td>
                        <td>{s.started_at ? new Date(s.started_at).toLocaleString() : '—'}</td>
                        <td>{canCICDApprove && String(s.status || '').toLowerCase() === 'pending_approval' ? <button className="btn btn-sm btn-success" onClick={()=>approveBuildManualGate(selectedBuild)}>Approve</button> : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Variables Tab ── */}
      {tab === 'vars' && canCICD && (
        <div className="card">
          <h3 style={{marginTop:0}}>Pipeline Variables</h3>
          <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:12}}>
            <select className="input" style={{width:240}} value={selectedPipeline||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedPipeline(v);fetchBuilds(v);}}>
              <option value="">Select pipeline</option>
              {pipelines.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          {selectedPipeline ? (
            <div>
              <div style={{display:'grid',gridTemplateColumns:'2fr 2fr 1fr 1fr 1fr',gap:8,marginBottom:12,alignItems:'center'}}>
                <input className="input" placeholder="Key" value={varForm.key} onChange={e=>setVarForm({...varForm,key:e.target.value})} />
                <input className="input" placeholder="Value" value={varForm.value} onChange={e=>setVarForm({...varForm,value:e.target.value})} />
                <label style={{display:'flex',alignItems:'center',gap:6}}><input type="checkbox" checked={varForm.is_secret} onChange={e=>setVarForm({...varForm,is_secret:e.target.checked})}/> Secret</label>
                <select className="input" value={varForm.status} onChange={e=>setVarForm({...varForm,status:e.target.value})}>
                  <option value="active">Active</option>
                  <option value="disabled">Disabled</option>
                </select>
                <button className="btn btn-primary" onClick={saveVariable}>+ Add</button>
              </div>
              {variables.length === 0 ? <p style={{color:'#9ca3af'}}>No variables yet.</p> : (
                <table className="table"><thead><tr><th>Key</th><th>Value</th><th>Secret</th><th>Status</th><th></th></tr></thead><tbody>
                  {variables.map(v => (
                    <tr key={v.id}>
                      <td>{v.key}</td><td>{v.is_secret ? '••••' : v.value}</td><td>{v.is_secret?'Yes':'No'}</td><td>{statusBadge(v.status||'active')}</td>
                      <td><button className="btn btn-sm btn-danger" onClick={()=>deleteVariable(v.id)}>Delete</button></td>
                    </tr>
                  ))}
                </tbody></table>
              )}
            </div>
          ) : <p style={{color:'#9ca3af'}}>Select a pipeline to manage variables.</p>}
        </div>
      )}

      {/* ── Environments Tab ── */}
      {tab === 'envs' && canCICD && (
        <div className="card">
          <h3 style={{marginTop:0}}>Deployment Environments</h3>
          <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:12}}>
            <select className="input" style={{width:240}} value={selectedPipeline||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedPipeline(v);}}>
              <option value="">Select pipeline</option>
              {pipelines.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          {selectedPipeline ? (
            <div>
              <div style={{display:'grid',gridTemplateColumns:'2fr 2fr 1fr 1fr 1fr',gap:8,marginBottom:12,alignItems:'center'}}>
                <input className="input" placeholder="Name" value={envForm.name} onChange={e=>setEnvForm({...envForm,name:e.target.value})} />
                <input className="input" placeholder="Webhook URL (optional)" value={envForm.webhook_url} onChange={e=>setEnvForm({...envForm,webhook_url:e.target.value})} />
                <select className="input" value={envForm.status} onChange={e=>setEnvForm({...envForm,status:e.target.value})}>
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                  <option value="disabled">Disabled</option>
                </select>
                <label style={{display:'flex',alignItems:'center',gap:6}}><input type="checkbox" checked={envForm.requires_approval} onChange={e=>setEnvForm({...envForm,requires_approval:e.target.checked})}/> Requires approval</label>
                <input className="input" type="number" min="1" placeholder="Approval quorum" value={envForm.approval_quorum} onChange={e=>setEnvForm({...envForm,approval_quorum:e.target.value})} />
                <input className="input" type="number" min="1" placeholder="Approval SLA (min)" value={envForm.approval_sla_minutes} onChange={e=>setEnvForm({...envForm,approval_sla_minutes:e.target.value})} />
                <input className="input" type="number" min="1" placeholder="Escalate after (min)" value={envForm.escalation_after_minutes} onChange={e=>setEnvForm({...envForm,escalation_after_minutes:e.target.value})} />
                <input className="input" style={{gridColumn:'1/3'}} placeholder="Description" value={envForm.description} onChange={e=>setEnvForm({...envForm,description:e.target.value})} />
                <input className="input" style={{gridColumn:'3/6'}} placeholder="Approvers (comma separated)" value={envForm.approvers} onChange={e=>setEnvForm({...envForm,approvers:e.target.value})} />
                <input className="input" style={{gridColumn:'1/5'}} placeholder="Escalation targets (comma separated users/emails)" value={envForm.escalation_targets} onChange={e=>setEnvForm({...envForm,escalation_targets:e.target.value})} />
                <button className="btn btn-primary" onClick={saveEnvironment}>+ Add</button>
              </div>
              {environments.length === 0 ? <p style={{color:'#9ca3af'}}>No environments yet.</p> : (
                <table className="table"><thead><tr><th>Name</th><th>Approval</th><th>Quorum</th><th>SLA</th><th>Escalation</th><th>Webhook</th><th>Status</th><th></th></tr></thead><tbody>
                  {environments.map(ev => (
                    <tr key={ev.id}>
                      <td>{ev.name}</td><td>{ev.requires_approval?'Yes':'No'}</td><td>{ev.approval_quorum || 1}</td><td>{ev.approval_sla_minutes || 60}m</td><td>{ev.escalation_after_minutes || 120}m</td><td style={{fontSize:12}}>{ev.webhook_url||'—'}</td><td>{statusBadge(ev.status||'active')}</td>
                      <td><button className="btn btn-sm btn-danger" onClick={()=>deleteEnvironment(ev.id)}>Delete</button></td>
                    </tr>
                  ))}
                </tbody></table>
              )}
            </div>
          ) : <p style={{color:'#9ca3af'}}>Select a pipeline to manage environments.</p>}
        </div>
      )}

      {/* ── Deployments Tab ── */}
      {tab === 'deploy' && canCICD && canCICDView && (
        <div className="card">
          <h3 style={{marginTop:0}}>Deployments</h3>
          <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:12,flexWrap:'wrap'}}>
            <select className="input" style={{width:240}} value={selectedPipeline||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedPipeline(v);}}>
              <option value="">Select pipeline</option>
              {pipelines.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <input className="input" type="number" min="1" style={{width:130}} value={evidenceDays} onChange={e=>setEvidenceDays(parseInt(e.target.value||30))} />
            <button className="btn btn-sm" onClick={()=>downloadApprovalEvidence('csv')}>Download Evidence CSV</button>
            <button className="btn btn-sm" onClick={()=>downloadApprovalEvidence('pdf')}>Download Evidence PDF</button>
          </div>
          {selectedPipeline ? (
            <div>
              <div style={{display:'grid',gridTemplateColumns:'1.2fr 1fr 1fr 1fr 1fr 0.8fr',gap:8,marginBottom:12,alignItems:'center'}}>
                <select className="input" value={depForm.environment} onChange={e=>setDepForm({...depForm,environment:e.target.value})}>
                  <option value="">Environment</option>
                  {environments.map(ev=><option key={ev.id} value={ev.name}>{ev.name}</option>)}
                </select>
                <input className="input" placeholder="Build ID (optional)" value={depForm.build_id} onChange={e=>setDepForm({...depForm,build_id:e.target.value})} />
                <input className="input" placeholder="External URL" value={depForm.external_url} onChange={e=>setDepForm({...depForm,external_url:e.target.value})} />
                <input className="input" placeholder="Storage path (optional)" value={depForm.storage_path} onChange={e=>setDepForm({...depForm,storage_path:e.target.value})} />
                <select className="input" value={depForm.status} onChange={e=>setDepForm({...depForm,status:e.target.value})}>
                  <option value="pending">Pending</option>
                  <option value="running">Running</option>
                  <option value="success">Success</option>
                  <option value="failed">Failed</option>
                  <option value="rolled_back">Rolled back</option>
                </select>
                <button className="btn btn-primary" onClick={createDeployment} disabled={!canCICDExecute}>+ Deploy</button>
                <input className="input" style={{gridColumn:'1/-1'}} placeholder="Notes" value={depForm.notes} onChange={e=>setDepForm({...depForm,notes:e.target.value})} />
              </div>
              {deployments.length === 0 ? <p style={{color:'#9ca3af'}}>No deployments yet.</p> : (
                <table className="table"><thead><tr><th>ID</th><th>Environment</th><th>Status</th><th>SLA</th><th>Escalation</th><th>Notify</th><th>Storage</th><th>Build</th><th>Started</th><th>Approved By</th><th>Actions</th></tr></thead><tbody>
                  {deployments.map(d => (
                    <tr key={d.id}>
                      <td>#{d.id}</td>
                      <td>{d.environment_name || d.environment_id}</td>
                      <td>{statusBadge(d.status)}</td>
                      <td>{d.approval_remaining_human ? `${d.approval_remaining_human}${d.approval_overdue ? ' overdue' : ''}` : '—'}</td>
                      <td>{d.escalation_status || '—'}</td>
                      <td>{d.escalation_notification_sent ? 'sent' : '—'}</td>
                      <td style={{fontSize:12}}>{d.storage_path || '—'}</td>
                      <td>{d.build_id||'—'}</td>
                      <td>{d.started_at?new Date(d.started_at).toLocaleString():'—'}</td>
                      <td>{d.approved_by||'—'}</td>
                      <td style={{display:'flex',gap:6}}>
                        {canCICDApprove && String(d.status || '').toLowerCase() === 'pending_approval' ? (
                          <>
                            <button className="btn btn-sm btn-success" onClick={()=>decideDeployment(d.id, 'approve')}>Approve</button>
                            <button className="btn btn-sm btn-danger" onClick={()=>decideDeployment(d.id, 'reject')}>Reject</button>
                          </>
                        ) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody></table>
              )}
            </div>
          ) : <p style={{color:'#9ca3af'}}>Select a pipeline to manage deployments.</p>}
        </div>
      )}

      {/* ── Artifacts Tab ── */}
      {tab === 'artifacts' && canCICD && (
        <div className="card">
          <h3 style={{marginTop:0}}>Build Artifacts</h3>
          <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:12}}>
            <select className="input" style={{width:200}} value={selectedBuild||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedBuild(v);}}>
              <option value="">Select build</option>
              {builds.map(b=><option key={b.id} value={b.id}>{b.pipeline_name} / #{b.build_number}</option>)}
            </select>
            <input type="file" onChange={e=>uploadArtifact(e.target.files[0])} />
          </div>
          {selectedBuild ? (
            artifacts.length === 0 ? <p style={{color:'#9ca3af'}}>No artifacts.</p> : (
              <ul>
                {artifacts.map(a => (
                  <li key={a.id} style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
                    <a href={`${API}${a.url}`} target="_blank" rel="noreferrer">{a.name}</a>
                    <span style={{color:'#9ca3af'}}>({a.size_bytes} bytes)</span>
                    {a.status && <span className="badge badge-secondary" style={{fontSize:10}}>{a.status}</span>}
                    {(a.meta?.release_managed || a.meta?.release_version) && <span className="badge badge-success" style={{fontSize:10}}>release {a.meta?.release_version || ''}</span>}
                    {a.storage_path && <span style={{fontSize:11,color:'#9ca3af'}}>{a.storage_path}</span>}
                    <button className="btn btn-sm btn-secondary" onClick={()=>markReleaseArtifact(a, 'release')}>Mark Release</button>
                    <button className="btn btn-sm btn-primary" onClick={()=>markReleaseArtifact(a, 'promote')}>Promote</button>
                  </li>
                ))}
              </ul>
            )
          ) : <p style={{color:'#9ca3af'}}>Select a build to view artifacts.</p>}
          <div className="card" style={{marginTop:12}}>
            <h4 style={{marginTop:0}}>Release Artifacts</h4>
            {releaseArtifacts.length === 0 ? (
              <p style={{color:'#9ca3af'}}>No release-managed artifacts yet.</p>
            ) : (
              <table className="table">
                <thead><tr><th>Name</th><th>Version</th><th>Channel</th><th>Status</th><th>Promotions</th></tr></thead>
                <tbody>
                  {releaseArtifacts.slice(0, 100).map((a) => (
                    <tr key={`release-${a.id}`}>
                      <td>{a.name}</td>
                      <td>{a.meta?.release_version || '—'}</td>
                      <td>{a.meta?.release_channel || '—'}</td>
                      <td>{a.status || '—'}</td>
                      <td>{(a.meta?.promotions || []).length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* ── Logs Tab ── */}
      {tab === 'logs' && canCICD && (
        <div className="card">
          <h3 style={{marginTop:0}}>Build Logs</h3>
          <div style={{display:'flex',gap:8,alignItems:'center',marginBottom:12}}>
            <select className="input" style={{width:200}} value={selectedBuild||''} onChange={e=>{const v=e.target.value?parseInt(e.target.value):null;setSelectedBuild(v);}}>
              <option value="">Select build</option>
              {builds.map(b=><option key={b.id} value={b.id}>{b.pipeline_name} / #{b.build_number}</option>)}
            </select>
            <button className="btn btn-sm" onClick={()=>{if(selectedBuild){fetchLogs(selectedBuild);}}}>Refresh</button>
          </div>
          {selectedBuild ? (
            logs.length === 0 ? <p style={{color:'#9ca3af'}}>No logs yet.</p> : (
              <div style={{maxHeight:300,overflow:'auto',background:'#0b1120',color:'#e5e7eb',padding:12,borderRadius:8,fontFamily:'monospace',fontSize:12}}>
                {logs.map(l => (
                  <div key={l.id} style={{marginBottom:4,display:'flex',gap:8,alignItems:'center'}}>
                    <span className="badge badge-info" style={{fontSize:10}}>{(l.status||'info').toUpperCase()}</span>
                    {l.storage_path && <span style={{color:'#9ca3af'}}>{l.storage_path}</span>}
                    <span>[{l.created_at}] {l.line}</span>
                  </div>
                ))}
              </div>
            )
          ) : <p style={{color:'#9ca3af'}}>Select a build to view logs.</p>}
        </div>
      )}

      {tab === 'rbac' && canCICD && (
        <div className="card">
          <h3 style={{marginTop:0}}>CI/CD RBAC Matrix</h3>
          {!hasRole('admin') ? (
            <p style={{color:'#9ca3af'}}>Only admin can change CI/CD permissions.</p>
          ) : rbacUsers.length === 0 ? (
            <p style={{color:'#9ca3af'}}>No users found.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>View</th>
                  <th>Manage</th>
                  <th>Execute</th>
                  <th>Approve</th>
                  <th>Save</th>
                </tr>
              </thead>
              <tbody>
                {rbacUsers.map(u => {
                  const p = u.custom_permissions || {};
                  const e = u.effective_permissions || {};
                  return (
                    <tr key={`rbac-${u.id}`}>
                      <td>{u.username}</td>
                      <td>{u.role}</td>
                      <td><input type="checkbox" checked={p.cicd_view ?? e.cicd_view ?? false} onChange={ev=>setUserCicdPerm(u.id,'cicd_view',ev.target.checked)} /></td>
                      <td><input type="checkbox" checked={p.cicd_manage ?? e.cicd_manage ?? false} onChange={ev=>setUserCicdPerm(u.id,'cicd_manage',ev.target.checked)} /></td>
                      <td><input type="checkbox" checked={p.cicd_execute ?? e.cicd_execute ?? false} onChange={ev=>setUserCicdPerm(u.id,'cicd_execute',ev.target.checked)} /></td>
                      <td><input type="checkbox" checked={p.cicd_approve ?? e.cicd_approve ?? false} onChange={ev=>setUserCicdPerm(u.id,'cicd_approve',ev.target.checked)} /></td>
                      <td><button className="btn btn-sm btn-primary" disabled={rbacSaving} onClick={()=>saveUserCicdPerms(u)}>Save</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Repositories Tab ── */}
      {tab === 'repositories' && canGit && (
        <div>
          {!selectedRepo ? (
            <div>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
                <h3>Git Repositories</h3>
                <button className="btn btn-primary" onClick={()=>setShowRepoForm(!showRepoForm)}>{showRepoForm ? 'Cancel' : 'Connect Git Server / Repository'}</button>
              </div>

              {showRepoForm && (
                <div className="card" style={{marginBottom:20,padding:20}}>
                  <h4 style={{marginBottom:12}}>Connect New Git Server / Repository</h4>
                  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:12}}>
                    <div>
                      <label>Name</label>
                      <input className="form-control" value={repoForm.name} onChange={e=>setRepoForm({...repoForm, name:e.target.value})} placeholder="My Project" />
                    </div>
                    <div>
                      <label>Provider</label>
                      <select className="form-control" value={repoForm.provider} onChange={e=>setRepoForm({...repoForm, provider:e.target.value})}>
                        <option value="gitlab">GitLab</option>
                        <option value="bitbucket">Bitbucket</option>
                        <option value="gitbucket">GitBucket (Self-hosted)</option>
                      </select>
                    </div>
                    {(repoForm.provider === 'gitlab' || repoForm.provider === 'gitbucket') && (
                      <div style={{gridColumn:'1/3'}}>
                        <label>Server URL</label>
                        <input className="form-control" value={repoForm.server_url} onChange={e=>setRepoForm({...repoForm, server_url:e.target.value})} placeholder={repoForm.provider === 'gitbucket' ? 'http://your-server:8080' : 'https://gitlab.example.com'} />
                      </div>
                    )}
                    <div>
                      <label>Repository Full Name</label>
                      <input className="form-control" value={repoForm.repo_full_name} onChange={e=>setRepoForm({...repoForm, repo_full_name:e.target.value})} placeholder="owner/repo-name" />
                    </div>
                    <div>
                      <label>Default Branch</label>
                      <input className="form-control" value={repoForm.default_branch} onChange={e=>setRepoForm({...repoForm, default_branch:e.target.value})} placeholder="main" />
                    </div>
                    <div style={{gridColumn:'1/3'}}>
                      <label>Access Token</label>
                      <input className="form-control" type="password" value={repoForm.auth_token} onChange={e=>setRepoForm({...repoForm, auth_token:e.target.value})} placeholder="Personal access token / App password" />
                    </div>
                  </div>
                  <div style={{marginTop:12,display:'flex',gap:8}}>
                    <button className="btn btn-primary" onClick={saveRepo}>Save & Connect</button>
                    {repoForm.auth_token && <button className="btn btn-info" onClick={discoverRepos} disabled={discoverLoading}>{discoverLoading ? 'Discovering...' : 'Discover Repos'}</button>}
                  </div>

                  {discoverResults && (
                    <div style={{marginTop:16}}>
                      <h5>Discovered Repositories ({discoverResults.length})</h5>
                      <div style={{maxHeight:250,overflowY:'auto',border:'1px solid #374151',borderRadius:8,padding:8}}>
                        {discoverResults.map((dr,i) => (
                          <div key={i} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'6px 8px',borderBottom:'1px solid #1f2937'}}>
                            <div>
                              <strong>{dr.full_name}</strong>
                              <span style={{marginLeft:8,fontSize:12,color:'#9ca3af'}}>{dr.description ? dr.description.substring(0,60) : ''}</span>
                              {dr.private && <span style={{marginLeft:6,background:'#f59e0b',color:'#000',padding:'1px 6px',borderRadius:10,fontSize:11}}>Private</span>}
                            </div>
                            <button className="btn btn-sm btn-success" onClick={()=>{setRepoForm({...repoForm, name:dr.full_name.split('/')[1]||dr.full_name, repo_full_name:dr.full_name, default_branch:dr.default_branch||'main'})}}>Quick Fill</button>
                          </div>
                        ))}
                        {discoverResults.length === 0 && <p style={{color:'#9ca3af',textAlign:'center',padding:16}}>No repositories found. Check your token permissions.</p>}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {gitLoading ? <p>Loading repositories...</p> : gitRepos.length === 0 ? (
                <div className="card" style={{textAlign:'center',padding:40}}>
                  <p style={{fontSize:32,marginBottom:8,fontWeight:800}}>REPO</p>
                  <p style={{color:'#9ca3af'}}>No repositories connected yet. Click "Connect Git Server / Repository" to get started.</p>
                </div>
              ) : (
                <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(340px,1fr))',gap:16}}>
                  {gitRepos.map(repo => (
                    <div key={repo.id} className="card" style={{padding:16,cursor:'pointer',border:repo.is_active ? '1px solid #10b981' : '1px solid #374151'}} onClick={()=>openRepoDetail(repo)}>
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start'}}>
                        <div>
                          <span style={{fontSize:20,marginRight:6}}>
                            <AppIcon name={repo.provider === 'gitlab' ? 'pipeline' : repo.provider === 'bitbucket' ? 'archive' : 'database'} size={18} />
                          </span>
                          <strong>{repo.name}</strong>
                          <span style={{marginLeft:8,background:'#374151',padding:'2px 8px',borderRadius:10,fontSize:11,textTransform:'uppercase'}}>{repo.provider}</span>
                        </div>
                        <span style={{width:10,height:10,borderRadius:'50%',background:repo.is_active ? '#10b981' : '#ef4444',display:'inline-block',marginTop:6}}></span>
                      </div>
                      <p style={{color:'#9ca3af',fontSize:13,margin:'8px 0 4px'}}>{repo.repo_full_name}</p>
                      <div style={{display:'flex',gap:8,fontSize:12,color:'#6b7280'}}>
                        <span>{repo.default_branch}</span>
                        {repo.webhook_id && <span>Webhook active</span>}
                        {repo.last_synced && <span>{new Date(repo.last_synced).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            /* ── Repo Detail View ── */
            <div>
              <button className="btn btn-secondary" onClick={()=>setSelectedRepo(null)} style={{marginBottom:12}}>← Back to Repositories</button>
              <div className="card" style={{padding:20,marginBottom:16}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                  <div>
                    <span style={{fontSize:24,marginRight:8}}>
                      <AppIcon name={selectedRepo.provider === 'gitlab' ? 'pipeline' : selectedRepo.provider === 'bitbucket' ? 'archive' : 'database'} size={18} />
                    </span>
                    <h3 style={{display:'inline'}}>{selectedRepo.name}</h3>
                    <span style={{marginLeft:12,background:'#374151',padding:'2px 10px',borderRadius:10,fontSize:12,textTransform:'uppercase'}}>{selectedRepo.provider}</span>
                    <span style={{marginLeft:8,background:selectedRepo.is_active ? '#065f46' : '#7f1d1d',padding:'2px 10px',borderRadius:10,fontSize:12}}>{selectedRepo.is_active ? 'Active' : 'Inactive'}</span>
                  </div>
                  <div style={{display:'flex',gap:6}}>
                    <button className="btn btn-sm btn-info" onClick={()=>testRepoConn(selectedRepo.id)}>Test</button>
                    <button className="btn btn-sm btn-primary" onClick={()=>syncRepo(selectedRepo.id)}>Sync</button>
                    {!selectedRepo.webhook_id ? <button className="btn btn-sm btn-success" onClick={()=>registerWebhook(selectedRepo.id)}>Add Webhook</button>
                      : <button className="btn btn-sm btn-warning" onClick={()=>removeWebhook(selectedRepo.id)}>Remove Webhook</button>}
                    <button className="btn btn-sm btn-danger" onClick={()=>deleteRepo(selectedRepo.id)}>Delete</button>
                  </div>
                </div>
                <p style={{color:'#9ca3af',marginTop:8}}>{selectedRepo.repo_full_name} • Branch: {selectedRepo.default_branch} {selectedRepo.last_synced && ` • Last synced: ${new Date(selectedRepo.last_synced).toLocaleString()}`}</p>
              </div>

              {/* Sub-tabs */}
              <div style={{display:'flex',gap:4,marginBottom:16,flexWrap:'wrap'}}>
                {[{k:'info',l:'Info'},{k:'branches',l:'Branches'},{k:'commits',l:'Commits'},{k:'pulls',l:'Pull Requests'},{k:'tags',l:'Tags'},{k:'files',l:'Files'}].map(t => (
                  <button key={t.k} className={`btn btn-sm ${repoSubTab===t.k ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={()=>{
                      setRepoSubTab(t.k);
                      if (t.k==='branches') loadRepoBranches(selectedRepo.id);
                      if (t.k==='commits') loadRepoCommits(selectedRepo.id);
                      if (t.k==='pulls') loadRepoPulls(selectedRepo.id);
                      if (t.k==='tags') loadRepoTags(selectedRepo.id);
                      if (t.k==='files') { setTreePath(''); setRepoFile(null); loadRepoTree(selectedRepo.id,''); }
                    }}>{t.l}</button>
                ))}
              </div>

              {/* Info Sub-tab */}
              {repoSubTab === 'info' && (
                <div className="card" style={{padding:20}}>
                  <h4>Repository Information</h4>
                  <table style={{width:'100%',marginTop:12}}>
                    <tbody>
                      {[['Name', selectedRepo.name],['Provider', selectedRepo.provider],['Full Name', selectedRepo.repo_full_name],['Default Branch', selectedRepo.default_branch],['Server URL', selectedRepo.server_url || 'Default (cloud)'],['Webhook ID', selectedRepo.webhook_id || 'None'],['Created', new Date(selectedRepo.created_at).toLocaleString()],['Last Synced', selectedRepo.last_synced ? new Date(selectedRepo.last_synced).toLocaleString() : 'Never']].map(([k,v]) => (
                        <tr key={k}><td style={{padding:'6px 12px',color:'#9ca3af',width:160}}>{k}</td><td style={{padding:'6px 12px'}}>{v}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  {selectedRepo.repo_meta && (
                    <div style={{marginTop:16}}>
                      <h5>Metadata</h5>
                      <div style={{display:'flex',gap:16,flexWrap:'wrap',marginTop:8}}>
                        {selectedRepo.repo_meta.stars != null && <span>{selectedRepo.repo_meta.stars} stars</span>}
                        {selectedRepo.repo_meta.forks != null && <span>{selectedRepo.repo_meta.forks} forks</span>}
                        {selectedRepo.repo_meta.open_issues != null && <span>{selectedRepo.repo_meta.open_issues} issues</span>}
                        {selectedRepo.repo_meta.language && <span>{selectedRepo.repo_meta.language}</span>}
                        {selectedRepo.repo_meta.description && <p style={{width:'100%',color:'#9ca3af',marginTop:8}}>{selectedRepo.repo_meta.description}</p>}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Branches Sub-tab */}
              {repoSubTab === 'branches' && (
                <div className="card" style={{padding:20}}>
                  <h4>Branches ({repoBranches.length})</h4>
                  {repoBranches.length === 0 ? <p style={{color:'#9ca3af'}}>Loading branches...</p> : (
                    <table style={{width:'100%',marginTop:12}}>
                      <thead><tr><th style={{textAlign:'left',padding:6}}>Branch</th><th style={{textAlign:'left',padding:6}}>Latest Commit</th></tr></thead>
                      <tbody>{repoBranches.map((b,i) => (
                        <tr key={i}><td style={{padding:6}}>
                          {b.name}{b.name === selectedRepo.default_branch && <span style={{marginLeft:6,background:'#065f46',padding:'1px 6px',borderRadius:10,fontSize:11}}>default</span>}
                        </td><td style={{padding:6,color:'#9ca3af',fontSize:13}}>{b.sha ? b.sha.substring(0,8) : '—'}</td></tr>
                      ))}</tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Commits Sub-tab */}
              {repoSubTab === 'commits' && (
                <div className="card" style={{padding:20}}>
                  <h4>Recent Commits</h4>

                  {repoCommits.length === 0 ? <p style={{color:'#9ca3af'}}>Loading commits...</p> : (
                    <div style={{marginTop:12}}>
                      {repoCommits.map((c,i) => (
                        <div key={i} style={{borderBottom:'1px solid #1f2937',padding:'10px 0'}}>
                          <div style={{display:'flex',justifyContent:'space-between'}}>
                            <strong style={{fontSize:14}}>{c.message ? c.message.split('\n')[0] : '---'}</strong>
                            <code style={{color:'#60a5fa',fontSize:12}}>{c.sha ? c.sha.substring(0,8) : ''}</code>
                          </div>
                          <div style={{fontSize:12,color:'#6b7280',marginTop:4}}>
                            {c.author || 'Unknown'} - {c.date ? new Date(c.date).toLocaleString() : ''}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Pull Requests Sub-tab */}
              {repoSubTab === 'pulls' && (
                <div className="card" style={{padding:20}}>
                  <h4>Pull Requests / Merge Requests</h4>
                  {repoPulls.length === 0 ? <p style={{color:'#9ca3af'}}>No open pull requests.</p> : (
                    <div style={{marginTop:12}}>
                      {repoPulls.map((pr,i) => (
                        <div key={i} style={{borderBottom:'1px solid #1f2937',padding:'10px 0',display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                          <div>
                            <span style={{color:'#10b981',marginRight:6}}>#{pr.number}</span>
                            <strong>{pr.title}</strong>
                            <div style={{fontSize:12,color:'#6b7280',marginTop:4}}>by {pr.author || 'Unknown'} - {pr.created ? new Date(pr.created).toLocaleDateString() : ''}</div>
                          </div>
                          <span style={{background: pr.state === 'open' ? '#065f46' : pr.state === 'merged' ? '#581c87' : '#7f1d1d', padding:'2px 10px',borderRadius:10,fontSize:12}}>{pr.state || 'open'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Tags Sub-tab */}
              {repoSubTab === 'tags' && (
                <div className="card" style={{padding:20}}>
                  <h4>Tags</h4>
                  <button className="btn btn-sm btn-secondary" onClick={()=>loadRepoTags(selectedRepo.id)} style={{marginBottom:12}}>Refresh</button>
                  {repoTags.length === 0 ? <p style={{color:'#9ca3af'}}>No tags found.</p> : (
                    <table style={{width:'100%'}}>
                      <thead><tr><th style={{textAlign:'left',padding:6}}>Tag</th><th style={{textAlign:'left',padding:6}}>SHA</th></tr></thead>
                      <tbody>{repoTags.map((t,i) => (
                        <tr key={i}><td style={{padding:6}}>{t.name}</td><td style={{padding:6,color:'#9ca3af',fontSize:13}}>{t.sha ? t.sha.substring(0,8) : '---'}</td></tr>
                      ))}</tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Files Sub-tab */}
              {repoSubTab === 'files' && (
                <div className="card" style={{padding:20}}>
                  <h4>File Browser</h4>
                  <div style={{marginBottom:12,display:'flex',gap:8,alignItems:'center'}}>
                    <span style={{color:'#9ca3af',fontSize:13}}>Path:</span>
                    <span style={{color:'#60a5fa',fontSize:13,cursor:'pointer'}} onClick={()=>{setTreePath('');setRepoFile(null);loadRepoTree(selectedRepo.id,'');}}>root</span>
                    {treePath && treePath.split('/').map((seg,i,arr)=>{
                      const p = arr.slice(0,i+1).join('/');
                      return <span key={i}><span style={{color:'#6b7280'}}> / </span><span style={{color:'#60a5fa',fontSize:13,cursor:'pointer'}} onClick={()=>{setTreePath(p);setRepoFile(null);loadRepoTree(selectedRepo.id,p);}}>{seg}</span></span>;
                    })}
                  </div>

                  {repoFile ? (
                    <div>
                      <button className="btn btn-sm btn-secondary" onClick={()=>setRepoFile(null)} style={{marginBottom:8}}>← Back to tree</button>
                      <div style={{background:'#0d1117',padding:16,borderRadius:8,overflowX:'auto'}}>
                        <div style={{display:'flex',justifyContent:'space-between',marginBottom:8}}>
                          <strong>{repoFile.name}</strong>
                          <span style={{color:'#6b7280',fontSize:12}}>{repoFile.size ? `${(repoFile.size/1024).toFixed(1)} KB` : ''} • {repoFile.encoding || ''}</span>
                        </div>
                        <pre style={{margin:0,fontSize:13,lineHeight:1.5,color:'#e6edf3',whiteSpace:'pre-wrap',wordBreak:'break-all'}}>{repoFile.content || '(binary or empty)'}</pre>
                      </div>
                    </div>
                  ) : (
                    <div>
                      {repoTree.length === 0 ? <p style={{color:'#9ca3af'}}>Loading file tree...</p> : (
                        <table style={{width:'100%'}}>
                          <tbody>{repoTree.map((item,i) => (
                            <tr key={i} style={{cursor:'pointer',borderBottom:'1px solid #1f2937'}} onClick={()=>{
                              if (item.type === 'dir' || item.type === 'tree') {
                                const np = treePath ? `${treePath}/${item.name}` : item.name;
                                setTreePath(np); setRepoFile(null); loadRepoTree(selectedRepo.id, np);
                              } else {
                                const fp = treePath ? `${treePath}/${item.name}` : item.name;
                                loadRepoFile(selectedRepo.id, fp);
                              }
                            }}>
                              <td style={{padding:'6px 8px',width:30}}>{item.type === 'dir' || item.type === 'tree' ? 'DIR' : 'FILE'}</td>
                              <td style={{padding:'6px 8px',color: item.type === 'dir' || item.type === 'tree' ? '#60a5fa' : '#e5e7eb'}}>{item.name}</td>
                              <td style={{padding:'6px 8px',color:'#6b7280',fontSize:12,textAlign:'right'}}>{item.size ? `${(item.size/1024).toFixed(1)} KB` : ''}</td>
                            </tr>
                          ))}</tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Script Templates Tab ── */}
      {tab === 'scripts' && canCICD && (
        <div>
          <h3>Pipeline Script Templates</h3>
          <p style={{color:'#9ca3af',marginBottom:16}}>Ready-to-use pipeline scripts for Jenkins (Groovy), GitLab CI (YAML), and Shell. Copy and customize for your environment.</p>
          {Object.entries(templates).map(([key, tpl]) => (
            <div key={key} className="card" style={{marginBottom:16}}>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <h4 style={{margin:0}}>{tpl.label}</h4>
                <button className="btn btn-sm btn-primary" onClick={()=>{navigator.clipboard.writeText(tpl.content);setMsg(`${key} template copied to clipboard!`);}}>Copy</button>
              </div>
              <pre className="code-block" style={{marginTop:10,maxHeight:350,overflow:'auto',fontSize:11}}>{tpl.content}</pre>
            </div>
          ))}

          {/* Webhook setup guide */}
          <div className="card">
            <h4>Webhook Setup Guide</h4>
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))',gap:16}}>
              <div>
                <h5>Jenkins</h5>
                <ol style={{fontSize:13,paddingLeft:20}}>
                  <li>Install "Generic Webhook Trigger" plugin</li>
                  <li>In job config → Build Triggers → Generic Webhook Trigger</li>
                  <li>Set Token to your pipeline's webhook secret</li>
                  <li>For notifications back: Install "Notification" plugin, add webhook URL</li>
                  <li>Jenkinsfile supports Groovy declarative & scripted pipelines</li>
                </ol>
              </div>
              <div>
                <h5>GitLab CI</h5>
                <ol style={{fontSize:13,paddingLeft:20}}>
                  <li>Go to Settings → Webhooks</li>
                  <li>Enter the Patch-SecOps Solution webhook URL</li>
                  <li>Set Secret Token to your pipeline's webhook secret</li>
                  <li>Select "Pipeline events" trigger</li>
                  <li>Use <code>.gitlab-ci.yml</code> with YAML template</li>
                </ol>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Secrets Tab ── */}
      {tab === 'secrets' && canCICD && (
        <div>
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0 }}>Secret Manager</h3>
                <p style={{ color: '#9ca3af', margin: '4px 0 0', fontSize: 13 }}>
                  Encrypted secrets stored at rest. Reference in pipeline scripts as <code>{'${{ secrets.NAME }}'}</code>
                </p>
              </div>
              <button className="btn btn-sm" onClick={() => fetchSecrets(selectedPipeline)} disabled={secretsLoading}>
                {secretsLoading ? 'Loading...' : 'Refresh'}
              </button>
            </div>

            {secretMsg && (
              <div className="ops-command-card" style={{ marginBottom: 12, padding: '8px 14px' }}>{secretMsg}</div>
            )}

            {/* Create secret form */}
            {canCICDManage && (
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h4 style={{ margin: '0 0 12px' }}>Add Secret</h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <input className="input" placeholder="Secret name (e.g. DEPLOY_KEY)" value={secretForm.name}
                    onChange={e => setSecretForm(f => ({ ...f, name: e.target.value }))} />
                  <input className="input" placeholder="Description (optional)" value={secretForm.description}
                    onChange={e => setSecretForm(f => ({ ...f, description: e.target.value }))} />
                  <select className="input" value={secretForm.scope} onChange={e => setSecretForm(f => ({ ...f, scope: e.target.value }))}>
                    <option value="global">Global (all pipelines)</option>
                    <option value="pipeline">Pipeline-scoped</option>
                  </select>
                  {secretForm.scope === 'pipeline' && (
                    <select className="input" value={secretForm.pipeline_id} onChange={e => setSecretForm(f => ({ ...f, pipeline_id: e.target.value }))}>
                      <option value="">Select pipeline</option>
                      {pipelinesList.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  )}
                  <input className="input" type="password" placeholder="Secret value" value={secretForm.value}
                    onChange={e => setSecretForm(f => ({ ...f, value: e.target.value }))}
                    style={{ gridColumn: secretForm.scope === 'pipeline' ? '1/3' : '1/3' }} />
                </div>
                <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={async () => {
                  setSecretMsg('');
                  if (!secretForm.name.trim()) { setSecretMsg('Secret name is required'); return; }
                  if (!secretForm.value) { setSecretMsg('Secret value is required'); return; }
                  const body = {
                    name: secretForm.name.trim(),
                    description: secretForm.description,
                    scope: secretForm.scope,
                    pipeline_id: secretForm.scope === 'pipeline' && secretForm.pipeline_id ? Number(secretForm.pipeline_id) : null,
                    value: secretForm.value,
                  };
                  const r = await apiFetch(`${API}/api/cicd/secrets/`, { method: 'POST', body: JSON.stringify(body) });
                  const d = await r.json().catch(() => ({}));
                  if (r.ok) {
                    setSecretMsg(`Secret '${d.name}' created`);
                    setSecretForm({ name: '', description: '', scope: 'global', pipeline_id: '', value: '' });
                    fetchSecrets(selectedPipeline);
                  } else {
                    setSecretMsg(d.detail || 'Failed to create secret');
                  }
                }}>
                  Save Secret
                </button>
              </div>
            )}

            {/* Secrets table */}
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Scope</th>
                  <th>Pipeline</th>
                  <th>Description</th>
                  <th>Has Value</th>
                  <th>Created</th>
                  {canCICDManage && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {secrets.map(s => (
                  <tr key={s.id}>
                    <td><code>{s.name}</code></td>
                    <td><span className={`badge ${s.scope === 'global' ? 'badge-info' : 'badge-secondary'}`}>{s.scope}</span></td>
                    <td>{s.pipeline_id ? (pipelinesList.find(p => p.id === s.pipeline_id)?.name || `#${s.pipeline_id}`) : '—'}</td>
                    <td style={{ color: '#64748b', fontSize: 12 }}>{s.description || '—'}</td>
                    <td><span className={`badge ${s.has_value ? 'badge-success' : 'badge-danger'}`}>{s.has_value ? 'Set' : 'Empty'}</span></td>
                    <td style={{ fontSize: 11, color: '#64748b' }}>{s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
                    {canCICDManage && (
                      <td>
                        <button className="btn btn-sm btn-danger" onClick={async () => {
                          if (!window.confirm(`Delete secret '${s.name}'?`)) return;
                          const r = await apiFetch(`${API}/api/cicd/secrets/${s.id}`, { method: 'DELETE' });
                          if (r.ok) { setSecretMsg(`Deleted '${s.name}'`); fetchSecrets(selectedPipeline); }
                          else { const d = await r.json().catch(() => ({})); setSecretMsg(d.detail || 'Delete failed'); }
                        }}>Delete</button>
                      </td>
                    )}
                  </tr>
                ))}
                {!secrets.length && (
                  <tr><td colSpan={canCICDManage ? 7 : 6} style={{ textAlign: 'center', color: '#9ca3af', padding: 24 }}>
                    No secrets yet. Add one above.
                  </td></tr>
                )}
              </tbody>
            </table>

            <div style={{ marginTop: 16, padding: '12px 16px', background: '#f0f9ff', borderRadius: 8, border: '1px solid #bae6fd', fontSize: 13 }}>
              <strong>Usage:</strong> In your pipeline script, reference secrets as <code>{'${{ secrets.SECRET_NAME }}'}</code>.
              Secrets are resolved at build time and never appear in logs.
            </div>
          </div>
        </div>
      )}

      {/* ── Agent Targets Tab ── */}
      {tab === 'agent-targets' && canCICD && (
        <div>
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ margin: 0 }}>Agent Targets</h3>
                <p style={{ color: '#9ca3af', margin: '4px 0 0', fontSize: 13 }}>
                  Map pipeline environments to specific hosts. Stages with <code>runner_label: agent</code> or a matching label will execute on the target host via the Patch-SecOps Solution agent.
                </p>
              </div>
              <button className="btn btn-sm" onClick={() => { fetchAgentTargets(selectedPipeline); fetchHosts(); }} disabled={agentTargetsLoading}>
                {agentTargetsLoading ? 'Loading...' : 'Refresh'}
              </button>
            </div>

            {agentTargetMsg && (
              <div className="ops-command-card" style={{ marginBottom: 12, padding: '8px 14px' }}>{agentTargetMsg}</div>
            )}

            {/* Add target form */}
            {canCICDManage && (
              <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 16, marginBottom: 20 }}>
                <h4 style={{ margin: '0 0 12px' }}>Add Agent Target</h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                  <select className="input" value={targetForm.pipeline_id} onChange={e => setTargetForm(f => ({ ...f, pipeline_id: e.target.value }))}>
                    <option value="">Select pipeline</option>
                    {pipelinesList.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  <select className="input" value={targetForm.environment_id} onChange={e => setTargetForm(f => ({ ...f, environment_id: e.target.value }))}>
                    <option value="">Any environment</option>
                    {environments.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </select>
                  <select className="input" value={targetForm.host_id} onChange={e => setTargetForm(f => ({ ...f, host_id: e.target.value }))}>
                    <option value="">Select host</option>
                    {hosts.map(h => <option key={h.id} value={h.id}>{h.hostname} ({h.ip})</option>)}
                  </select>
                  <input className="input" placeholder="Label (e.g. prod-deploy)" value={targetForm.label}
                    onChange={e => setTargetForm(f => ({ ...f, label: e.target.value }))} />
                  <input className="input" placeholder="Run as user (optional)" value={targetForm.run_as}
                    onChange={e => setTargetForm(f => ({ ...f, run_as: e.target.value }))} />
                  <input className="input" placeholder="Working directory (optional)" value={targetForm.working_dir}
                    onChange={e => setTargetForm(f => ({ ...f, working_dir: e.target.value }))} />
                </div>
                <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={async () => {
                  setAgentTargetMsg('');
                  if (!targetForm.pipeline_id) { setAgentTargetMsg('Select a pipeline'); return; }
                  if (!targetForm.host_id) { setAgentTargetMsg('Select a host'); return; }
                  const body = {
                    pipeline_id: Number(targetForm.pipeline_id),
                    environment_id: targetForm.environment_id ? Number(targetForm.environment_id) : null,
                    host_id: Number(targetForm.host_id),
                    label: targetForm.label.trim(),
                    run_as: targetForm.run_as.trim(),
                    working_dir: targetForm.working_dir.trim(),
                    is_active: true,
                  };
                  const r = await apiFetch(`${API}/api/cicd/agent-targets/`, { method: 'POST', body: JSON.stringify(body) });
                  const d = await r.json().catch(() => ({}));
                  if (r.ok) {
                    setAgentTargetMsg(`Target added: ${d.hostname || d.host_ip}`);
                    setTargetForm({ pipeline_id: '', environment_id: '', host_id: '', label: '', run_as: '', working_dir: '', is_active: true });
                    fetchAgentTargets(selectedPipeline);
                  } else {
                    setAgentTargetMsg(d.detail || 'Failed to add target');
                  }
                }}>
                  Add Target
                </button>
              </div>
            )}

            {/* Targets table */}
            <table className="table">
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>Environment</th>
                  <th>Host</th>
                  <th>IP</th>
                  <th>Label</th>
                  <th>Run As</th>
                  <th>Working Dir</th>
                  <th>Active</th>
                  {canCICDManage && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {agentTargets.map(t => (
                  <tr key={t.id}>
                    <td>{pipelinesList.find(p => p.id === t.pipeline_id)?.name || `#${t.pipeline_id}`}</td>
                    <td>{t.environment_id ? (environments.find(e => e.id === t.environment_id)?.name || `#${t.environment_id}`) : '—'}</td>
                    <td><strong>{t.hostname || '—'}</strong></td>
                    <td><code style={{ fontSize: 11 }}>{t.host_ip || '—'}</code></td>
                    <td><code>{t.label || '—'}</code></td>
                    <td style={{ fontSize: 12, color: '#64748b' }}>{t.run_as || '—'}</td>
                    <td style={{ fontSize: 12, color: '#64748b' }}>{t.working_dir || '—'}</td>
                    <td><span className={`badge ${t.is_active ? 'badge-success' : 'badge-secondary'}`}>{t.is_active ? 'Active' : 'Inactive'}</span></td>
                    {canCICDManage && (
                      <td style={{ display: 'flex', gap: 6 }}>
                        <button className="btn btn-sm" onClick={async () => {
                          const r = await apiFetch(`${API}/api/cicd/agent-targets/${t.id}`, { method: 'PUT', body: JSON.stringify({ is_active: !t.is_active }) });
                          if (r.ok) fetchAgentTargets(selectedPipeline);
                        }}>{t.is_active ? 'Disable' : 'Enable'}</button>
                        <button className="btn btn-sm btn-danger" onClick={async () => {
                          if (!window.confirm('Delete this agent target?')) return;
                          const r = await apiFetch(`${API}/api/cicd/agent-targets/${t.id}`, { method: 'DELETE' });
                          if (r.ok) { setAgentTargetMsg('Target deleted'); fetchAgentTargets(selectedPipeline); }
                        }}>Delete</button>
                      </td>
                    )}
                  </tr>
                ))}
                {!agentTargets.length && (
                  <tr><td colSpan={canCICDManage ? 9 : 8} style={{ textAlign: 'center', color: '#9ca3af', padding: 24 }}>
                    No agent targets configured. Add one above.
                  </td></tr>
                )}
              </tbody>
            </table>

            {/* Agent Runs */}
            <div style={{ marginTop: 24 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <h4 style={{ margin: 0 }}>Recent Agent Runs</h4>
                <button className="btn btn-sm" onClick={() => fetchAgentRuns()}>Refresh</button>
              </div>
              <table className="table">
                <thead>
                  <tr><th>Run ID</th><th>Build</th><th>Host IP</th><th>Stage</th><th>Status</th><th>Exit</th><th>Started</th><th>Output</th></tr>
                </thead>
                <tbody>
                  {agentRuns.slice(0, 50).map(r => (
                    <tr key={r.id}>
                      <td>#{r.id}</td>
                      <td>#{r.build_id}</td>
                      <td><code style={{ fontSize: 11 }}>{r.host_ip}</code></td>
                      <td>{r.stage_name}</td>
                      <td><span className={`badge badge-${r.status === 'success' ? 'success' : r.status === 'failed' ? 'danger' : r.status === 'running' ? 'info' : 'warning'}`}>{r.status}</span></td>
                      <td>{r.exit_code ?? '—'}</td>
                      <td style={{ fontSize: 11, color: '#64748b' }}>{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</td>
                      <td style={{ maxWidth: 300 }}>
                        <details>
                          <summary style={{ cursor: 'pointer', fontSize: 12 }}>View output</summary>
                          <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto', background: '#1e293b', color: '#e2e8f0', padding: 8, borderRadius: 4, marginTop: 4 }}>{r.output || '(empty)'}</pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                  {!agentRuns.length && (
                    <tr><td colSpan={8} style={{ textAlign: 'center', color: '#9ca3af', padding: 24 }}>No agent runs yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: 16, padding: '12px 16px', background: '#f0fdf4', borderRadius: 8, border: '1px solid #bbf7d0', fontSize: 13 }}>
              <strong>How it works:</strong> In your pipeline JSON script, set <code>runner_label</code> on a stage to match a target label (or use <code>"agent"</code> to match all active targets for the pipeline). The stage command will be dispatched to the host via the Patch-SecOps Solution agent <code>/run</code> endpoint and the output streamed back into the build log.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Backup Manager ─── */
