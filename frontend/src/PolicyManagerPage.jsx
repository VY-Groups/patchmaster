import React, { useEffect, useMemo, useState } from 'react';

const sampleYaml = `name: "Web Server Hardening"
steps:
  - name: "Install Nginx"
    module: package
    state: installed
    package: nginx
  - name: "Ensure Nginx Running"
    module: service
    service: nginx
    state: running
    enable: true
  - name: "Secure SSH"
    module: file
    path: /etc/ssh/sshd_config
    state: present
    content: |
      PermitRootLogin no
      PasswordAuthentication no
`;

export default function PolicyManagerPage({ API, apiFetch }) {
  const [policies, setPolicies] = useState([]);
  const [hosts, setHosts] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [taskTemplates, setTaskTemplates] = useState([]);
  const [taskExecutions, setTaskExecutions] = useState([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState('');
  const [selectedRevisionId, setSelectedRevisionId] = useState('');
  const [selectedHosts, setSelectedHosts] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const [formData, setFormData] = useState({ name: '', description: '', yaml_content: sampleYaml, change_summary: '' });
  const [draftData, setDraftData] = useState({ name: '', description: '', yaml_content: '', change_summary: '' });
  const [taskForm, setTaskForm] = useState({ template_id: '', host_id: '', bundle_url: '' });

  // Defensive array checks
  const safePolicies = Array.isArray(policies) ? policies : [];
  const safeHosts = Array.isArray(hosts) ? hosts : [];
  const safeRevisions = Array.isArray(revisions) ? revisions : [];
  const safeExecutions = Array.isArray(executions) ? executions : [];
  const safeTaskTemplates = Array.isArray(taskTemplates) ? taskTemplates : [];
  const safeTaskExecutions = Array.isArray(taskExecutions) ? taskExecutions : [];

  const selectedPolicy = useMemo(
    () => safePolicies.find((policy) => String(policy.id) === String(selectedPolicyId)) || null,
    [safePolicies, selectedPolicyId]
  );

  const fetchAll = async () => {
    const [policyResp, hostResp, taskResp, taskExecResp] = await Promise.all([
      apiFetch(`${API}/api/policies/`),
      apiFetch(`${API}/api/hosts/`),
      apiFetch(`${API}/api/policies/admin-tasks/templates`),
      apiFetch(`${API}/api/policies/admin-tasks/executions`),
    ]);
    const [policyData, hostData, taskData, taskExecData] = await Promise.all([
      policyResp.json(),
      hostResp.json(),
      taskResp.json(),
      taskExecResp.json(),
    ]);
    setPolicies(Array.isArray(policyData) ? policyData : []);
    setHosts(Array.isArray(hostData) ? hostData : []);
    setTaskTemplates(taskData.items || []);
    setTaskExecutions(taskExecData.items || []);
    setSelectedPolicyId((current) => current || String(policyData?.[0]?.id || ''));
  };

  const fetchSelectedPolicy = async (policyId) => {
    if (!policyId) {
      setRevisions([]);
      setExecutions([]);
      return;
    }
    const [revResp, execResp] = await Promise.all([
      apiFetch(`${API}/api/policies/${policyId}/revisions`),
      apiFetch(`${API}/api/policies/${policyId}/executions`),
    ]);
    const [revData, execData] = await Promise.all([revResp.json(), execResp.json()]);
    setRevisions(revData.items || []);
    setExecutions(execData.items || []);
    setSelectedRevisionId((current) => current || String(revData.items?.[0]?.id || ''));
    if (!draftData.yaml_content) {
      const active = revData.items?.find((item) => item.status === 'active') || revData.items?.[0];
      if (active) setDraftData({ name: active.name || '', description: active.description || '', yaml_content: active.yaml_content || '', change_summary: '' });
    }
  };

  useEffect(() => { fetchAll().catch((error) => setNotice(error.message)); }, []);
  useEffect(() => { fetchSelectedPolicy(selectedPolicyId).catch((error) => setNotice(error.message)); }, [selectedPolicyId]);

  const createPolicy = async () => {
    setLoading(true);
    try {
      await apiFetch(`${API}/api/policies/`, { method: 'POST', body: JSON.stringify(formData) });
      setShowCreate(false);
      setFormData({ name: '', description: '', yaml_content: sampleYaml, change_summary: '' });
      setNotice('Policy created.');
      await fetchAll();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  };

  const saveDraft = async () => {
    if (!selectedPolicy) return;
    setLoading(true);
    try {
      await apiFetch(`${API}/api/policies/${selectedPolicy.id}`, { method: 'PUT', body: JSON.stringify(draftData) });
      setNotice('Draft revision saved.');
      await fetchAll();
      await fetchSelectedPolicy(selectedPolicy.id);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  };

  const runRevisionAction = async (action, revisionId = selectedRevisionId) => {
    if (!selectedPolicy || !revisionId || selectedHosts.length === 0) return;
    setLoading(true);
    try {
      const path = action === 'activate'
        ? `${API}/api/policies/${selectedPolicy.id}/revisions/${revisionId}/activate`
        : action === 'rollback'
          ? `${API}/api/policies/${selectedPolicy.id}/rollback/${revisionId}`
          : `${API}/api/policies/${selectedPolicy.id}/revisions/${revisionId}/${action}`;
      const body = action === 'activate' ? null : JSON.stringify({ host_ids: selectedHosts, guardrails: { require_dry_run: action === 'apply' } });
      await apiFetch(path, { method: 'POST', ...(body ? { body } : {}) });
      setNotice(`Policy ${action} completed.`);
      await fetchAll();
      await fetchSelectedPolicy(selectedPolicy.id);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  };

  const executeAdminTask = async () => {
    if (!taskForm.template_id || !taskForm.host_id) return;
    setLoading(true);
    try {
      const payload = {
        template_id: Number(taskForm.template_id),
        host_id: Number(taskForm.host_id),
        parameters: taskForm.bundle_url ? { bundle_url: taskForm.bundle_url } : {},
      };
      await apiFetch(`${API}/api/policies/admin-tasks/execute`, { method: 'POST', body: JSON.stringify(payload) });
      setNotice('Admin task queued.');
      setTaskForm({ template_id: '', host_id: '', bundle_url: '' });
      await fetchAll();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="card highlight-card">
        <h2>Configuration Policies And Admin Tasks</h2>
        <p>Patch-SecOps Solution now supports policy revisions, explicit activation, dry-runs, apply history, rollback, and reusable operator tasks from one workspace.</p>
      </div>
      {notice ? <div className="card" style={{ marginBottom: 16 }}><strong>Status:</strong> {notice}</div> : null}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3>Policies</h3>
          <button className="btn btn-primary" onClick={() => setShowCreate((v) => !v)}>{showCreate ? 'Close' : '+ New Policy'}</button>
        </div>
        {showCreate ? (
          <div style={{ display: 'grid', gap: 12, marginBottom: 20 }}>
            <input className="input" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder="Policy name" />
            <input className="input" value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} placeholder="Description" />
            <input className="input" value={formData.change_summary} onChange={(e) => setFormData({ ...formData, change_summary: e.target.value })} placeholder="Change summary" />
            <textarea className="input" style={{ height: 220, fontFamily: 'monospace' }} value={formData.yaml_content} onChange={(e) => setFormData({ ...formData, yaml_content: e.target.value })} />
            <button className="btn btn-primary" disabled={loading} onClick={createPolicy}>{loading ? 'Saving...' : 'Create Policy'}</button>
          </div>
        ) : null}
        {safePolicies.length === 0 ? <p>No policies defined.</p> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Active Revision</th><th>Latest</th><th>Execution</th></tr></thead>
            <tbody>
              {safePolicies.map((policy) => (
                <tr key={policy.id} style={{ cursor: 'pointer', background: String(policy.id) === String(selectedPolicyId) ? 'rgba(59,130,246,0.08)' : undefined }} onClick={() => setSelectedPolicyId(String(policy.id))}>
                  <td><strong>{policy.name}</strong><div style={{ fontSize: 12, color: '#64748b' }}>{policy.description}</div></td>
                  <td>{policy.active_revision?.revision_number || '--'}</td>
                  <td>{policy.latest_revision?.revision_number || '--'}</td>
                  <td>{policy.last_execution?.execution_mode || 'none'} / {policy.last_execution?.status || 'never'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedPolicy ? (
        <div className="grid-2">
          <div className="card">
            <h3>Revision Manager: {selectedPolicy.name}</h3>
            <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
              <input className="input" value={draftData.name} onChange={(e) => setDraftData({ ...draftData, name: e.target.value })} placeholder="Revision name" />
              <input className="input" value={draftData.description} onChange={(e) => setDraftData({ ...draftData, description: e.target.value })} placeholder="Revision description" />
              <input className="input" value={draftData.change_summary} onChange={(e) => setDraftData({ ...draftData, change_summary: e.target.value })} placeholder="Change summary" />
              <textarea className="input" style={{ height: 240, fontFamily: 'monospace' }} value={draftData.yaml_content} onChange={(e) => setDraftData({ ...draftData, yaml_content: e.target.value })} />
              <button className="btn btn-primary" disabled={loading} onClick={saveDraft}>{loading ? 'Saving...' : 'Save Draft Revision'}</button>
            </div>
            <div style={{ maxHeight: 260, overflowY: 'auto', border: '1px solid #334155', borderRadius: 6, padding: 10 }}>
              {safeRevisions.map((revision) => (
                <label key={revision.id} style={{ display: 'block', padding: '6px 0' }}>
                  <input type="radio" checked={String(selectedRevisionId) === String(revision.id)} onChange={() => setSelectedRevisionId(String(revision.id))} />
                  <span style={{ marginLeft: 8 }}>r{revision.revision_number} - {revision.status} - {revision.change_summary || revision.name}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Execution And Rollback</h3>
            <div style={{ maxHeight: 220, overflowY: 'auto', marginBottom: 16, border: '1px solid #334155', borderRadius: 6, padding: 10 }}>
              {safeHosts.map((host) => (
                <label key={host.id} style={{ display: 'block', padding: '4px 0' }}>
                  <input type="checkbox" checked={selectedHosts.includes(host.id)} onChange={(e) => setSelectedHosts((prev) => e.target.checked ? [...prev, host.id] : prev.filter((id) => id !== host.id))} />
                  <span style={{ marginLeft: 8 }}>{host.hostname} ({host.ip}){host.site ? ` - ${host.site}` : ''}</span>
                </label>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
              <button className="btn" disabled={loading || !selectedRevisionId || selectedHosts.length === 0} onClick={() => runRevisionAction('activate', selectedRevisionId)}>Activate Revision</button>
              <button className="btn btn-primary" disabled={loading || !selectedRevisionId || selectedHosts.length === 0} onClick={() => runRevisionAction('dry-run', selectedRevisionId)}>Dry-run</button>
              <button className="btn btn-primary" disabled={loading || !selectedRevisionId || selectedHosts.length === 0} onClick={() => runRevisionAction('apply', selectedRevisionId)}>Apply</button>
              <button className="btn" disabled={loading || !selectedRevisionId || selectedHosts.length === 0} onClick={() => runRevisionAction('rollback', selectedRevisionId)}>Rollback To Revision</button>
            </div>
            <table className="table">
              <thead><tr><th>Mode</th><th>Status</th><th>Requested By</th><th>Summary</th></tr></thead>
              <tbody>
                {safeExecutions.map((execution) => (
                  <tr key={execution.id}>
                    <td>{execution.execution_mode}</td>
                    <td>{execution.status}</td>
                    <td>{execution.requested_by}</td>
                    <td>{execution.summary?.succeeded || 0}/{execution.summary?.host_count || 0} success</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="card">
        <h3>Reusable Admin Tasks</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, marginBottom: 16 }}>
          <select className="input" value={taskForm.template_id} onChange={(e) => setTaskForm({ ...taskForm, template_id: e.target.value })}>
            <option value="">Select task template</option>
            {safeTaskTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
          </select>
          <select className="input" value={taskForm.host_id} onChange={(e) => setTaskForm({ ...taskForm, host_id: e.target.value })}>
            <option value="">Select host</option>
            {safeHosts.map((host) => <option key={host.id} value={host.id}>{host.hostname} ({host.ip})</option>)}
          </select>
          <input className="input" value={taskForm.bundle_url} onChange={(e) => setTaskForm({ ...taskForm, bundle_url: e.target.value })} placeholder="Optional bundle_url parameter" />
        </div>
        <button className="btn btn-primary" disabled={loading} onClick={executeAdminTask}>{loading ? 'Queuing...' : 'Run Admin Task'}</button>
        <table className="table" style={{ marginTop: 16 }}>
          <thead><tr><th>Task</th><th>Host</th><th>Status</th><th>Result</th></tr></thead>
          <tbody>
            {safeTaskExecutions.map((execution) => (
              <tr key={execution.id}>
                <td>{execution.template?.name || execution.task_key}</td>
                <td>{execution.host?.hostname || '--'}</td>
                <td>{execution.status}</td>
                <td>{execution.result_summary?.rc !== undefined ? `rc=${execution.result_summary.rc}` : execution.queue_job_id || '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
