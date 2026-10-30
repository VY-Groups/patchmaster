import React, { useEffect, useMemo, useState } from 'react';
import './OpsPages.css';

function workflowTone(status) {
  if (status === 'implemented') return 'badge-success';
  if (status === 'planned') return 'badge-info';
  return 'badge-secondary';
}

function sortedHosts(hosts) {
  return [...(hosts || [])].sort((left, right) => String(left.hostname || '').localeCompare(String(right.hostname || '')));
}

export default function NetworkBootPage({ hosts, API, apiFetch, useInterval, AppIcon }) {
  const [workflowCards, setWorkflowCards] = useState([]);
  const [networks, setNetworks] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [mirrorRepos, setMirrorRepos] = useState([]);
  const [relays, setRelays] = useState([]);
  const [bootSessions, setBootSessions] = useState([]);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [selectedRelayId, setSelectedRelayId] = useState('');
  const [artifactPreview, setArtifactPreview] = useState(null);
  const [servicePreview, setServicePreview] = useState(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [networkForm, setNetworkForm] = useState({
    name: '',
    interface_name: '',
    vlan_id: '',
    cidr: '',
    gateway: '',
    dns_servers: '',
    dhcp_range_start: '',
    dhcp_range_end: '',
    next_server: '',
    controller_url: '',
    relay_id: '',
    boot_file_bios: 'undionly.kpxe',
    boot_file_uefi: 'ipxe.efi',
  });
  const [relayForm, setRelayForm] = useState({
    name: '',
    host_id: '',
    site_scope: '',
    install_root: '/var/lib/patchmaster/network-boot',
    public_base_url: '',
    notes: '',
  });
  const [profileForm, setProfileForm] = useState({
    name: '',
    network_id: '',
    provisioning_template_id: '',
    mirror_repo_id: '',
    os_family: 'linux',
    os_version: '',
    architecture: 'x86_64',
    firmware_mode: 'uefi',
    install_mode: 'ubuntu_autoinstall',
    kernel_url: '',
    initrd_url: '',
    rootfs_url: '',
    answer_template: '',
    post_install_script: '',
    release_label: 'stable',
  });
  const [assignmentForm, setAssignmentForm] = useState({
    network_id: '',
    profile_id: '',
    host_id: '',
    hostname: '',
    mac_address: '',
    reserved_ip: '',
    firmware_mode: 'uefi',
    site_scope: '',
    boot_once: true,
  });

  const orderedHosts = useMemo(() => sortedHosts(hosts), [hosts]);
  const selectedProfile = useMemo(
    () => profiles.find((profile) => String(profile.id) === String(selectedProfileId)),
    [profiles, selectedProfileId]
  );
  const selectedRelay = useMemo(
    () => relays.find((relay) => String(relay.id) === String(selectedRelayId)),
    [relays, selectedRelayId]
  );

  const refreshWorkflows = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/workflows`);
      const payload = await response.json();
      setWorkflowCards(payload.items || payload.workflows || []);
    } catch {
      setWorkflowCards([]);
    }
  };

  const refreshNetworks = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/networks`);
      const payload = await response.json();
      setNetworks(payload.items || []);
      setProfileForm((current) => {
        const currentId = String(current.network_id || '');
        const stillExists = (payload.items || []).some((item) => String(item.id) === currentId);
        return { ...current, network_id: stillExists ? currentId : String(payload.items?.[0]?.id || '') };
      });
      setAssignmentForm((current) => {
        const currentId = String(current.network_id || '');
        const stillExists = (payload.items || []).some((item) => String(item.id) === currentId);
        return { ...current, network_id: stillExists ? currentId : String(payload.items?.[0]?.id || '') };
      });
    } catch {
      setNetworks([]);
    }
  };

  const refreshProfiles = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/profiles`);
      const payload = await response.json();
      setProfiles(payload.items || []);
      setSelectedProfileId((current) => {
        if (current && (payload.items || []).some((item) => String(item.id) === String(current))) {
          return current;
        }
        return String(payload.items?.[0]?.id || '');
      });
      setAssignmentForm((current) => {
        const currentId = String(current.profile_id || '');
        const stillExists = (payload.items || []).some((item) => String(item.id) === currentId);
        return { ...current, profile_id: stillExists ? currentId : String(payload.items?.[0]?.id || '') };
      });
    } catch {
      setProfiles([]);
    }
  };

  const refreshCatalog = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/catalog`);
      const payload = await response.json();
      setTemplates(payload.provisioning_templates || []);
      setMirrorRepos(payload.mirror_repositories || []);
      setProfileForm((current) => {
        const currentId = String(current.provisioning_template_id || '');
        const stillExists = (payload.provisioning_templates || []).some((item) => String(item.id) === currentId);
        const currentMirrorId = String(current.mirror_repo_id || '');
        const mirrorStillExists = (payload.mirror_repositories || []).some((item) => String(item.id) === currentMirrorId);
        return {
          ...current,
          provisioning_template_id: stillExists ? currentId : '',
          mirror_repo_id: mirrorStillExists ? currentMirrorId : '',
        };
      });
    } catch {
      setTemplates([]);
      setMirrorRepos([]);
    }
  };

  const refreshAssignments = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/assignments`);
      const payload = await response.json();
      setAssignments(payload.items || []);
    } catch {
      setAssignments([]);
    }
  };

  const refreshServicePreview = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/service-preview`);
      const payload = await response.json();
      setServicePreview(response.ok ? payload : null);
    } catch {
      setServicePreview(null);
    }
  };

  const refreshRelays = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/relays`);
      const payload = await response.json();
      const items = payload.items || [];
      setRelays(items);
      setSelectedRelayId((current) => {
        if (current && items.some((item) => String(item.id) === String(current))) return current;
        return String(items[0]?.id || '');
      });
      setNetworkForm((current) => {
        const currentId = String(current.relay_id || '');
        const stillExists = items.some((item) => String(item.id) === currentId);
        return { ...current, relay_id: stillExists ? currentId : '' };
      });
    } catch {
      setRelays([]);
    }
  };

  const refreshBootSessions = async () => {
    try {
      const response = await apiFetch(`${API}/api/network-boot/boot-sessions?limit=25`);
      const payload = await response.json();
      setBootSessions(payload.items || []);
    } catch {
      setBootSessions([]);
    }
  };

  const refreshAll = async () => {
    await Promise.all([
      refreshWorkflows(),
      refreshNetworks(),
      refreshProfiles(),
      refreshCatalog(),
      refreshAssignments(),
      refreshRelays(),
      refreshBootSessions(),
      refreshServicePreview(),
    ]);
  };

  const loadPreview = async (profileId) => {
    if (!profileId) {
      setArtifactPreview(null);
      return;
    }
    try {
      const response = await apiFetch(`${API}/api/network-boot/profiles/${profileId}/artifact-preview`);
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not load artifact preview.');
        return;
      }
      setArtifactPreview(payload);
    } catch (error) {
      setNotice(error.message);
    }
  };

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    if (selectedProfileId) {
      loadPreview(selectedProfileId);
    } else {
      setArtifactPreview(null);
    }
  }, [selectedProfileId]);

  useInterval(() => {
    refreshProfiles();
    refreshAssignments();
    refreshRelays();
    refreshBootSessions();
  }, 15000);

  const createNetwork = async () => {
    if (!networkForm.name.trim()) {
      setNotice('Boot network name is required.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/network-boot/networks`, {
        method: 'POST',
        body: JSON.stringify({
          ...networkForm,
          name: networkForm.name.trim(),
          interface_name: networkForm.interface_name.trim(),
          vlan_id: networkForm.vlan_id === '' ? null : Number(networkForm.vlan_id),
          cidr: networkForm.cidr.trim(),
          gateway: networkForm.gateway.trim(),
          dns_servers: networkForm.dns_servers.split(',').map((value) => value.trim()).filter(Boolean),
          dhcp_range_start: networkForm.dhcp_range_start.trim(),
          dhcp_range_end: networkForm.dhcp_range_end.trim(),
          next_server: networkForm.next_server.trim(),
          controller_url: networkForm.controller_url.trim(),
          relay_id: networkForm.relay_id ? Number(networkForm.relay_id) : null,
          boot_file_bios: networkForm.boot_file_bios.trim() || 'undionly.kpxe',
          boot_file_uefi: networkForm.boot_file_uefi.trim() || 'ipxe.efi',
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not create boot network.');
        return;
      }
      setNotice(`Boot network "${payload.name}" created.`);
      setNetworkForm({
        name: '',
        interface_name: '',
        vlan_id: '',
        cidr: '',
        gateway: '',
        dns_servers: '',
        dhcp_range_start: '',
        dhcp_range_end: '',
        next_server: '',
        controller_url: '',
        relay_id: '',
        boot_file_bios: 'undionly.kpxe',
        boot_file_uefi: 'ipxe.efi',
      });
      await refreshNetworks();
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const createProfile = async () => {
    if (!profileForm.name.trim()) {
      setNotice('Boot profile name is required.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/network-boot/profiles`, {
        method: 'POST',
        body: JSON.stringify({
          ...profileForm,
          name: profileForm.name.trim(),
          network_id: profileForm.network_id ? Number(profileForm.network_id) : null,
          provisioning_template_id: profileForm.provisioning_template_id ? Number(profileForm.provisioning_template_id) : null,
          mirror_repo_id: profileForm.mirror_repo_id ? Number(profileForm.mirror_repo_id) : null,
          os_family: profileForm.os_family.trim(),
          os_version: profileForm.os_version.trim(),
          architecture: profileForm.architecture.trim() || 'x86_64',
          firmware_mode: profileForm.firmware_mode,
          install_mode: profileForm.install_mode,
          kernel_url: profileForm.kernel_url.trim(),
          initrd_url: profileForm.initrd_url.trim(),
          rootfs_url: profileForm.rootfs_url.trim(),
          answer_template: profileForm.answer_template,
          post_install_script: profileForm.post_install_script,
          release_label: profileForm.release_label.trim() || 'stable',
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not create boot profile.');
        return;
      }
      setNotice(`Boot profile "${payload.name}" created.`);
      setProfileForm((current) => ({
        ...current,
        name: '',
        os_version: '',
        kernel_url: '',
        initrd_url: '',
        rootfs_url: '',
        answer_template: '',
        post_install_script: '',
      }));
      await refreshProfiles();
      setSelectedProfileId(String(payload.id));
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const createRelay = async () => {
    if (!relayForm.name.trim() || !relayForm.host_id) {
      setNotice('Relay name and managed host are required.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/network-boot/relays`, {
        method: 'POST',
        body: JSON.stringify({
          name: relayForm.name.trim(),
          host_id: Number(relayForm.host_id),
          site_scope: relayForm.site_scope.trim(),
          install_root: relayForm.install_root.trim(),
          public_base_url: relayForm.public_base_url.trim(),
          notes: relayForm.notes,
          is_enabled: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not create boot relay.');
        return;
      }
      setNotice(`Boot relay "${payload.name}" created.`);
      setRelayForm({
        name: '',
        host_id: '',
        site_scope: '',
        install_root: '/var/lib/patchmaster/network-boot',
        public_base_url: '',
        notes: '',
      });
      await refreshRelays();
      setSelectedRelayId(String(payload.id));
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const runRelayAction = async (relayId, action) => {
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/network-boot/relays/${relayId}/${action}`, { method: 'POST' });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || `Could not ${action} relay.`);
        return;
      }
      setNotice(`Relay action queued: ${action}.`);
      await Promise.all([refreshRelays(), refreshBootSessions()]);
    } catch (error) {
      setNotice(error.message);
    }
  };

  const createAssignment = async () => {
    if (!assignmentForm.network_id || !assignmentForm.profile_id || !assignmentForm.mac_address.trim()) {
      setNotice('Network, profile, and MAC address are required for a PXE assignment.');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const selectedHost = orderedHosts.find((host) => String(host.id) === String(assignmentForm.host_id || ''));
      const response = await apiFetch(`${API}/api/network-boot/assignments`, {
        method: 'POST',
        body: JSON.stringify({
          network_id: Number(assignmentForm.network_id),
          profile_id: Number(assignmentForm.profile_id),
          host_id: assignmentForm.host_id ? Number(assignmentForm.host_id) : null,
          hostname: assignmentForm.hostname.trim() || selectedHost?.hostname || '',
          mac_address: assignmentForm.mac_address.trim(),
          reserved_ip: assignmentForm.reserved_ip.trim(),
          firmware_mode: assignmentForm.firmware_mode,
          site_scope: assignmentForm.site_scope.trim() || selectedHost?.site || '',
          boot_once: Boolean(assignmentForm.boot_once),
          is_enabled: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setNotice(payload.detail || payload.error?.message || 'Could not create PXE assignment.');
        return;
      }
      setNotice(`PXE assignment created for ${payload.hostname || payload.mac_address}.`);
      setAssignmentForm((current) => ({
        ...current,
        host_id: '',
        hostname: '',
        mac_address: '',
        reserved_ip: '',
        site_scope: '',
        boot_once: true,
      }));
      await Promise.all([refreshAssignments(), refreshServicePreview()]);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  };

  const downloadDeploymentBundle = async () => {
    setNotice('');
    try {
      const response = await apiFetch(`${API}/api/network-boot/deployment-bundle`);
      if (!response.ok) {
        const payload = await response.json();
        setNotice(payload.detail || payload.error?.message || 'Could not download deployment bundle.');
        return;
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'patchmaster-network-boot-bundle.tar.gz';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      setNotice('PXE deployment bundle downloaded.');
    } catch (error) {
      setNotice(error.message);
    }
  };

  const downloadRelayBundle = async (relay) => {
    setNotice('');
    try {
      const response = await apiFetch(`${API}/boot/network-boot/relays/${relay.id}/bundle.tar.gz`);
      if (!response.ok) {
        const payload = await response.json();
        setNotice(payload.detail || payload.error?.message || 'Could not download relay bundle.');
        return;
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `patchmaster-boot-relay-${relay.id}.tar.gz`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
      setNotice(`Relay bundle downloaded for ${relay.name}.`);
    } catch (error) {
      setNotice(error.message);
    }
  };

  return (
    <div className="ops-shell">
      <div className="ops-hero">
        <div className="ops-hero-main" style={{ borderColor: '#c7d2fe', background: 'linear-gradient(145deg, #eef2ff, #f8fbff)' }}>
          <div className="ops-kicker">Bare-metal deployment workspace</div>
          <div className="ops-hero-row">
            <div className="ops-hero-emphasis">
              <span className="ops-emphasis-label">Managed-relay status</span>
              <span className="ops-emphasis-value" style={{ color: '#4338ca', fontSize: 28 }}>Active</span>
              <span className="ops-emphasis-meta">Controller-managed relays, published artifacts, per-host assignments, and live boot-session telemetry.</span>
            </div>
            <div className="ops-hero-copy">
              <h3>Design, publish, and export a real bare-metal rollout stack from one operator workspace.</h3>
              <p>
                This workspace now goes beyond planning. Operators can define boot networks, separate the boot-host URL from the Patch-SecOps Solution controller URL, build reusable install profiles, assign them to specific MAC addresses, publish iPXE and answer endpoints, and download a deployment bundle containing dnsmasq, nginx, and boot-host installer artifacts for a dedicated PXE host.
              </p>
            </div>
          </div>
          <div className="ops-chip-row">
            <span className="ops-chip">Boot networks</span>
            <span className="ops-chip">Install profiles</span>
            <span className="ops-chip">Published iPXE</span>
            <span className="ops-chip">Enrollment answers</span>
            <span className="ops-chip">Golden image linkage</span>
            <span className="ops-chip">Deployment bundle</span>
            <span className="ops-chip">Managed relays</span>
            <span className="ops-chip">Boot-session telemetry</span>
          </div>
        </div>
        <div className="ops-hero-side">
          <span className="ops-side-label">Deployment model</span>
          <div className="ops-side-metric">Managed relays</div>
          <p className="ops-side-note">
            Patch-SecOps Solution now binds managed hosts as PXE relays, generates relay-scoped bundles, validates relay services, and records boot-session evidence back in the controller.
          </p>
          <div className="ops-inline-list">
            <div className="ops-inline-card">
                <strong>{workflowCards.length}</strong>
              <span>workflow blocks</span>
            </div>
            <div className="ops-inline-card">
              <strong>{networks.length}</strong>
              <span>boot networks</span>
            </div>
            <div className="ops-inline-card">
              <strong>{profiles.length}</strong>
              <span>boot profiles</span>
            </div>
            <div className="ops-inline-card">
              <strong>{templates.length}</strong>
              <span>linked image templates</span>
            </div>
            <div className="ops-inline-card">
              <strong>{assignments.length}</strong>
              <span>PXE assignments</span>
            </div>
            <div className="ops-inline-card">
              <strong>{relays.length}</strong>
              <span>managed relays</span>
            </div>
            <div className="ops-inline-card">
              <strong>{bootSessions.length}</strong>
              <span>live boot sessions</span>
            </div>
          </div>
        </div>
      </div>

      {notice ? (
        <div className="ops-panel" style={{ borderColor: '#cbd5e1', background: 'linear-gradient(180deg, #ffffff, #f8fafc)' }}>
          <div className="ops-panel-title" style={{ fontSize: 15 }}>Status</div>
          <p className="ops-subtle" style={{ marginTop: 8 }}>{notice}</p>
        </div>
      ) : null}

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Managed bare-metal workflow</div>
            <p className="ops-subtle">These blocks describe the complete operator workflow from network definition to relay operation and enrollment evidence.</p>
          </div>
          <button className="btn btn-sm" onClick={refreshWorkflows}>Refresh workflow</button>
        </div>
        <div className="ops-summary-grid">
          {workflowCards.map((workflow) => (
            <div key={workflow.id || workflow.label || workflow.title} className="ops-summary-card">
              <div className="ops-summary-head">
                <div className="ops-summary-icon" style={{ background: 'rgba(99, 102, 241, 0.1)', color: '#4338ca' }}>
                  <AppIcon name={workflow.status === 'implemented' ? 'rocket' : 'timeline'} size={18} />
                </div>
                <div>
                  <div className="ops-summary-label">{workflow.label || workflow.id}</div>
                  <div className="ops-summary-value" style={{ fontSize: 18 }}>{workflow.title}</div>
                </div>
              </div>
              <div className="ops-summary-sub">
                <span className={`badge ${workflowTone(workflow.status)}`}>{workflow.status}</span>
                <div className="ops-list" style={{ marginTop: 12 }}>
                  {(workflow.capabilities || []).map((item) => (
                    <div key={item} className="ops-list-copy">
                      <strong style={{ fontSize: 13 }}>{item}</strong>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Managed boot relays</div>
              <p className="ops-subtle">Register a normal PatchMaster-managed host as a relay, then install, sync, validate, and download its scoped bundle from here.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <div>
              <label className="ops-side-label">Relay name</label>
              <input className="input" value={relayForm.name} onChange={(event) => setRelayForm((current) => ({ ...current, name: event.target.value }))} placeholder="mumbai-hq-relay-01" />
            </div>
            <div>
              <label className="ops-side-label">Managed host</label>
              <select className="input" value={relayForm.host_id} onChange={(event) => setRelayForm((current) => ({ ...current, host_id: event.target.value }))}>
                <option value="">Select host</option>
                {orderedHosts.map((host) => (
                  <option key={host.id} value={host.id}>{host.hostname} ({host.ip}){host.site ? ` - ${host.site}` : ''}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">Site / location</label>
              <input className="input" value={relayForm.site_scope} onChange={(event) => setRelayForm((current) => ({ ...current, site_scope: event.target.value }))} placeholder="Mumbai-HQ" />
            </div>
            <div>
              <label className="ops-side-label">Install root</label>
              <input className="input" value={relayForm.install_root} onChange={(event) => setRelayForm((current) => ({ ...current, install_root: event.target.value }))} />
            </div>
            <div>
              <label className="ops-side-label">Public base URL</label>
              <input className="input" value={relayForm.public_base_url} onChange={(event) => setRelayForm((current) => ({ ...current, public_base_url: event.target.value }))} placeholder="http://10.42.120.20" />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label className="ops-side-label">Notes</label>
              <textarea className="input" rows={3} value={relayForm.notes} onChange={(event) => setRelayForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Optional operator notes" />
            </div>
          </div>
          <div className="ops-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" disabled={busy} onClick={createRelay}>{busy ? 'Saving...' : 'Register relay'}</button>
            <button className="btn btn-sm" onClick={refreshRelays}>Refresh relays</button>
          </div>
          <div className="ops-list" style={{ marginTop: 18 }}>
            {relays.length === 0 ? (
              <div className="ops-empty">No managed boot relays yet.</div>
            ) : relays.map((relay) => (
              <div key={relay.id} className="ops-list-row">
                <div className="ops-list-copy">
                  <strong>{relay.name}</strong>
                  <span>{relay.host?.hostname || 'Unbound host'} | {relay.host?.ip || '--'}{relay.site_scope ? ` | ${relay.site_scope}` : ''}</span>
                  <span>Version: {relay.applied_version || 'not applied'} | Validate: {relay.last_validation_status || 'not run'}</span>
                </div>
                <div className="ops-chip-row" style={{ justifyContent: 'flex-end' }}>
                  <span className="badge badge-info">{relay.status || 'idle'}</span>
                  <button className="btn btn-sm" onClick={() => runRelayAction(relay.id, 'install')}>Install</button>
                  <button className="btn btn-sm" onClick={() => runRelayAction(relay.id, 'sync')}>Sync</button>
                  <button className="btn btn-sm" onClick={() => runRelayAction(relay.id, 'validate')}>Validate</button>
                  <button className="btn btn-sm" onClick={() => downloadRelayBundle(relay)}>Bundle</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Live boot sessions</div>
              <p className="ops-subtle">Watch assignment-served, installer, and enrollment events as they flow back from the boot process.</p>
            </div>
            <button className="btn btn-sm" onClick={refreshBootSessions}>Refresh sessions</button>
          </div>
          <div className="ops-list">
            {bootSessions.length === 0 ? (
              <div className="ops-empty">No boot sessions yet.</div>
            ) : bootSessions.map((session) => (
              <div key={session.id} className="ops-list-row">
                <div className="ops-list-copy">
                  <strong>{session.hostname || session.assignment?.hostname || session.mac_address}</strong>
                  <span>{session.current_stage} | {session.status} | {session.provisioning_source || 'unknown source'}</span>
                  <span>{session.relay?.name ? `Relay: ${session.relay.name}` : 'No relay'}{session.controller_url ? ` | Controller: ${session.controller_url}` : ''}</span>
                  {session.events?.length ? <span>Latest event: {session.events[0].event_type} ({session.events[0].source})</span> : null}
                </div>
                <div className="ops-chip-row" style={{ justifyContent: 'flex-end' }}>
                  <span className="badge badge-info">{session.event_count || 0} events</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">3. Bind PXE assignments to real endpoints</div>
            <p className="ops-subtle">Map a MAC address to a boot profile so pre-agent machines receive the right iPXE chain and enrollment answer on first boot.</p>
          </div>
        </div>
        <div className="ops-form-grid">
          <div>
            <label className="ops-side-label">Boot network</label>
            <select className="input" value={assignmentForm.network_id} onChange={(event) => setAssignmentForm((current) => ({ ...current, network_id: event.target.value }))}>
              <option value="">Select network</option>
              {networks.map((network) => (
                <option key={network.id} value={network.id}>{network.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="ops-side-label">Boot profile</label>
            <select className="input" value={assignmentForm.profile_id} onChange={(event) => setAssignmentForm((current) => ({ ...current, profile_id: event.target.value }))}>
              <option value="">Select profile</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="ops-side-label">Managed host (optional)</label>
            <select className="input" value={assignmentForm.host_id} onChange={(event) => setAssignmentForm((current) => ({ ...current, host_id: event.target.value }))}>
              <option value="">Unmanaged bare-metal target</option>
              {orderedHosts.map((host) => (
                <option key={host.id} value={host.id}>{host.hostname}{host.site ? ` (${host.site})` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="ops-side-label">Hostname override</label>
            <input className="input" value={assignmentForm.hostname} onChange={(event) => setAssignmentForm((current) => ({ ...current, hostname: event.target.value }))} placeholder="branch-a-lt-01" />
          </div>
          <div>
            <label className="ops-side-label">MAC address</label>
            <input className="input" value={assignmentForm.mac_address} onChange={(event) => setAssignmentForm((current) => ({ ...current, mac_address: event.target.value }))} placeholder="AA-BB-CC-DD-EE-FF" />
          </div>
          <div>
            <label className="ops-side-label">Reserved IP</label>
            <input className="input" value={assignmentForm.reserved_ip} onChange={(event) => setAssignmentForm((current) => ({ ...current, reserved_ip: event.target.value }))} placeholder="10.42.120.50" />
          </div>
          <div>
            <label className="ops-side-label">Firmware mode</label>
            <select className="input" value={assignmentForm.firmware_mode} onChange={(event) => setAssignmentForm((current) => ({ ...current, firmware_mode: event.target.value }))}>
              <option value="uefi">UEFI</option>
              <option value="bios">BIOS</option>
              <option value="mixed">Mixed</option>
            </select>
          </div>
          <div>
            <label className="ops-side-label">Site / location</label>
            <input className="input" value={assignmentForm.site_scope} onChange={(event) => setAssignmentForm((current) => ({ ...current, site_scope: event.target.value }))} placeholder="London-Branch-A" />
          </div>
        </div>
        <div className="ops-actions" style={{ marginTop: 16 }}>
          <button className="btn btn-primary" disabled={busy} onClick={createAssignment}>{busy ? 'Saving...' : 'Create PXE assignment'}</button>
          <button className="btn btn-sm" onClick={refreshAssignments}>Refresh assignments</button>
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">1. Define a boot network</div>
            <p className="ops-subtle">Capture the boot-host delivery URL, the Patch-SecOps Solution controller URL, and the DHCP or firmware values your bare-metal rollout stack needs.</p>
          </div>
        </div>
          <div className="ops-form-grid">
            <div>
              <label className="ops-side-label">Network name</label>
              <input className="input" value={networkForm.name} onChange={(event) => setNetworkForm((current) => ({ ...current, name: event.target.value }))} placeholder="Branch-London-UEFI" />
            </div>
            <div>
              <label className="ops-side-label">Interface</label>
              <input className="input" value={networkForm.interface_name} onChange={(event) => setNetworkForm((current) => ({ ...current, interface_name: event.target.value }))} placeholder="bond0.120" />
            </div>
            <div>
              <label className="ops-side-label">VLAN</label>
              <input className="input" value={networkForm.vlan_id} onChange={(event) => setNetworkForm((current) => ({ ...current, vlan_id: event.target.value }))} placeholder="120" />
            </div>
            <div>
              <label className="ops-side-label">CIDR</label>
              <input className="input" value={networkForm.cidr} onChange={(event) => setNetworkForm((current) => ({ ...current, cidr: event.target.value }))} placeholder="10.42.120.0/24" />
            </div>
            <div>
              <label className="ops-side-label">Gateway</label>
              <input className="input" value={networkForm.gateway} onChange={(event) => setNetworkForm((current) => ({ ...current, gateway: event.target.value }))} placeholder="10.42.120.1" />
            </div>
            <div>
              <label className="ops-side-label">DNS servers</label>
              <input className="input" value={networkForm.dns_servers} onChange={(event) => setNetworkForm((current) => ({ ...current, dns_servers: event.target.value }))} placeholder="10.42.0.10, 10.42.0.11" />
            </div>
            <div>
              <label className="ops-side-label">DHCP range start</label>
              <input className="input" value={networkForm.dhcp_range_start} onChange={(event) => setNetworkForm((current) => ({ ...current, dhcp_range_start: event.target.value }))} placeholder="10.42.120.100" />
            </div>
            <div>
              <label className="ops-side-label">DHCP range end</label>
              <input className="input" value={networkForm.dhcp_range_end} onChange={(event) => setNetworkForm((current) => ({ ...current, dhcp_range_end: event.target.value }))} placeholder="10.42.120.199" />
            </div>
            <div>
              <label className="ops-side-label">Next server / HTTP boot base</label>
              <input className="input" value={networkForm.next_server} onChange={(event) => setNetworkForm((current) => ({ ...current, next_server: event.target.value }))} placeholder="http://boot.branch.local" />
            </div>
            <div>
              <label className="ops-side-label">Patch-SecOps Solution controller URL</label>
              <input className="input" value={networkForm.controller_url} onChange={(event) => setNetworkForm((current) => ({ ...current, controller_url: event.target.value }))} placeholder="http://patchmaster-core.local:8000" />
            </div>
            <div>
              <label className="ops-side-label">Managed relay</label>
              <select className="input" value={networkForm.relay_id} onChange={(event) => setNetworkForm((current) => ({ ...current, relay_id: event.target.value }))}>
                <option value="">Unbound</option>
                {relays.map((relay) => (
                  <option key={relay.id} value={relay.id}>{relay.name}{relay.site_scope ? ` (${relay.site_scope})` : ''}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">BIOS boot file</label>
              <input className="input" value={networkForm.boot_file_bios} onChange={(event) => setNetworkForm((current) => ({ ...current, boot_file_bios: event.target.value }))} />
            </div>
            <div>
              <label className="ops-side-label">UEFI boot file</label>
              <input className="input" value={networkForm.boot_file_uefi} onChange={(event) => setNetworkForm((current) => ({ ...current, boot_file_uefi: event.target.value }))} />
            </div>
          </div>
          <div className="ops-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" disabled={busy} onClick={createNetwork}>{busy ? 'Saving...' : 'Create boot network'}</button>
            <button className="btn btn-sm" onClick={refreshNetworks}>Refresh networks</button>
          </div>
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">2. Create a boot profile</div>
              <p className="ops-subtle">Combine OS installer inputs, firmware expectations, and optional golden-image references into a reusable rollout design.</p>
            </div>
          </div>
          <div className="ops-form-grid">
            <div>
              <label className="ops-side-label">Profile name</label>
              <input className="input" value={profileForm.name} onChange={(event) => setProfileForm((current) => ({ ...current, name: event.target.value }))} placeholder="Ubuntu-24.04-Branch-Autoinstall" />
            </div>
            <div>
              <label className="ops-side-label">Boot network</label>
              <select className="input" value={profileForm.network_id} onChange={(event) => setProfileForm((current) => ({ ...current, network_id: event.target.value }))}>
                <option value="">Unassigned</option>
                {networks.map((network) => (
                  <option key={network.id} value={network.id}>{network.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">Provisioning template</label>
              <select className="input" value={profileForm.provisioning_template_id} onChange={(event) => setProfileForm((current) => ({ ...current, provisioning_template_id: event.target.value }))}>
                <option value="">Installer-only profile</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>{template.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">Mirror-backed source</label>
              <select className="input" value={profileForm.mirror_repo_id} onChange={(event) => setProfileForm((current) => ({ ...current, mirror_repo_id: event.target.value }))}>
                <option value="">Direct URL / installer media</option>
                {mirrorRepos.map((repo) => (
                  <option key={repo.id} value={repo.id}>{repo.name}{repo.is_ready ? '' : ' (not ready)'}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="ops-side-label">OS family</label>
              <select className="input" value={profileForm.os_family} onChange={(event) => setProfileForm((current) => ({ ...current, os_family: event.target.value }))}>
                <option value="linux">Linux</option>
                <option value="windows">Windows</option>
                <option value="mixed">Mixed</option>
              </select>
            </div>
            <div>
              <label className="ops-side-label">OS version</label>
              <input className="input" value={profileForm.os_version} onChange={(event) => setProfileForm((current) => ({ ...current, os_version: event.target.value }))} placeholder="24.04 / 9.5 / 11 24H2" />
            </div>
            <div>
              <label className="ops-side-label">Architecture</label>
              <input className="input" value={profileForm.architecture} onChange={(event) => setProfileForm((current) => ({ ...current, architecture: event.target.value }))} />
            </div>
            <div>
              <label className="ops-side-label">Firmware mode</label>
              <select className="input" value={profileForm.firmware_mode} onChange={(event) => setProfileForm((current) => ({ ...current, firmware_mode: event.target.value }))}>
                <option value="uefi">UEFI</option>
                <option value="bios">BIOS</option>
                <option value="mixed">Mixed</option>
              </select>
            </div>
            <div>
              <label className="ops-side-label">Install mode</label>
              <select className="input" value={profileForm.install_mode} onChange={(event) => setProfileForm((current) => ({ ...current, install_mode: event.target.value }))}>
                <option value="ubuntu_autoinstall">Ubuntu Autoinstall</option>
                <option value="rocky_kickstart">Rocky Kickstart</option>
                <option value="windows_autounattend">Windows Autounattend</option>
                <option value="image_restore">Image Restore</option>
              </select>
            </div>
            <div>
              <label className="ops-side-label">Kernel URL / bootmgr</label>
              <input className="input" value={profileForm.kernel_url} onChange={(event) => setProfileForm((current) => ({ ...current, kernel_url: event.target.value }))} placeholder="Optional override" />
            </div>
            <div>
              <label className="ops-side-label">Initrd URL / boot.sdi</label>
              <input className="input" value={profileForm.initrd_url} onChange={(event) => setProfileForm((current) => ({ ...current, initrd_url: event.target.value }))} placeholder="Optional override" />
            </div>
            <div>
              <label className="ops-side-label">Rootfs URL / boot.wim</label>
              <input className="input" value={profileForm.rootfs_url} onChange={(event) => setProfileForm((current) => ({ ...current, rootfs_url: event.target.value }))} placeholder="Installer repo or image payload" />
            </div>
            <div>
              <label className="ops-side-label">Release label</label>
              <input className="input" value={profileForm.release_label} onChange={(event) => setProfileForm((current) => ({ ...current, release_label: event.target.value }))} />
            </div>
          </div>
          <div className="ops-form-grid" style={{ marginTop: 12 }}>
            <div>
              <label className="ops-side-label">Custom answer template</label>
              <textarea className="input" rows={6} value={profileForm.answer_template} onChange={(event) => setProfileForm((current) => ({ ...current, answer_template: event.target.value }))} placeholder="Leave blank to let Patch-SecOps Solution generate a managed-relay answer file with telemetry hooks." />
            </div>
            <div>
              <label className="ops-side-label">Post-install script</label>
              <textarea className="input" rows={6} value={profileForm.post_install_script} onChange={(event) => setProfileForm((current) => ({ ...current, post_install_script: event.target.value }))} placeholder="Optional first-boot or post-install steps." />
            </div>
          </div>
          <div className="ops-actions" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" disabled={busy} onClick={createProfile}>{busy ? 'Saving...' : 'Create boot profile'}</button>
            <button className="btn btn-sm" onClick={refreshProfiles}>Refresh profiles</button>
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Boot networks</div>
              <p className="ops-subtle">These define the managed relay, controller, and addressing environment for enterprise bare-metal rollout.</p>
            </div>
          </div>
          {networks.length === 0 ? (
            <div className="ops-empty">No boot networks yet. Define at least one network to anchor relay-bound rollout profiles.</div>
          ) : (
            <table className="table ops-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Addressing</th>
                  <th>Boot delivery</th>
                </tr>
              </thead>
              <tbody>
                {networks.map((network) => (
                  <tr key={network.id}>
                    <td>
                      <strong>{network.name}</strong>
                      <span className="ops-table-meta">{network.interface_name || 'No interface set'}{network.vlan_id ? ` | VLAN ${network.vlan_id}` : ''}</span>
                    </td>
                    <td>
                      {network.cidr || '-'}
                      <span className="ops-table-meta">Gateway {network.gateway || '-'} | DHCP {network.dhcp_range_start || '-'} → {network.dhcp_range_end || '-'}</span>
                    </td>
                    <td>
                      {network.next_server || 'patchmaster-boot.local'}
                      <span className="ops-table-meta">BIOS {network.boot_file_bios || '-'} | UEFI {network.boot_file_uefi || '-'}{network.relay?.name ? ` | Relay ${network.relay.name}` : ''}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">Boot profiles</div>
              <p className="ops-subtle">Profiles can be installer-based or image-based. Select one to preview generated artifacts.</p>
            </div>
            <select className="input" style={{ minWidth: 220 }} value={selectedProfileId} onChange={(event) => setSelectedProfileId(event.target.value)}>
              <option value="">Select profile</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
          </div>
          {profiles.length === 0 ? (
            <div className="ops-empty">No boot profiles yet. Create a profile to preview iPXE and answer files.</div>
          ) : (
            <div className="ops-list">
              {profiles.map((profile) => (
                <div key={profile.id} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{profile.name}</strong>
                    <span>{profile.install_mode} | {profile.firmware_mode} | {profile.network?.name || 'No network'}{profile.provisioning_template?.name ? ` | image ${profile.provisioning_template.name}` : ''}{profile.mirror_repo?.name ? ` | mirror ${profile.mirror_repo.name}` : ''}</span>
                  </div>
                  <div className="ops-actions">
                    <span className="badge badge-info">{profile.release_label || 'stable'}</span>
                    <button className="btn btn-sm" onClick={() => setSelectedProfileId(String(profile.id))}>Preview</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Artifact preview</div>
            <p className="ops-subtle">Use this to validate the exact published iPXE and answer-file content that your bare-metal targets will consume.</p>
          </div>
          {selectedProfile ? (
            <div className="ops-actions">
              <span className="badge badge-light">{selectedProfile.install_mode}</span>
              <span className="badge badge-light">{selectedProfile.firmware_mode}</span>
            </div>
          ) : null}
        </div>
        {!artifactPreview ? (
          <div className="ops-empty">Choose a boot profile to render the generated boot artifacts.</div>
        ) : (
          <>
            <div className="ops-detail-grid">
              <div className="ops-detail-item">
                <span>Profile root</span>
                <strong>{artifactPreview.artifact_urls?.profile_root || '-'}</strong>
              </div>
              <div className="ops-detail-item">
                <span>Linked template</span>
                <strong>{artifactPreview.profile?.provisioning_template?.name || 'Installer-only profile'}</strong>
              </div>
              <div className="ops-detail-item">
                <span>Published boot URL</span>
                <strong>{artifactPreview.artifact_urls?.ipxe || '-'}</strong>
              </div>
              <div className="ops-detail-item">
                <span>Published answer URL</span>
                <strong>{artifactPreview.artifact_urls?.answer || '-'}</strong>
              </div>
            </div>
            <div className="grid-2">
              <div className="ops-command-card">
                <div className="ops-side-label">Generated iPXE script</div>
                <pre className="ops-console">{artifactPreview.ipxe_script || '# No script generated'}</pre>
              </div>
              <div className="ops-command-card">
                <div className="ops-side-label">Generated answer template</div>
                <pre className="ops-console">{artifactPreview.answer_template || '# No answer template generated'}</pre>
              </div>
            </div>
            {artifactPreview.post_install_script ? (
              <div className="ops-command-card" style={{ marginTop: 16 }}>
                <div className="ops-side-label">Post-install script</div>
                <pre className="ops-console">{artifactPreview.post_install_script}</pre>
              </div>
            ) : null}
            <div className="ops-list" style={{ marginTop: 16 }}>
              {(artifactPreview.notes || []).map((item) => (
                <div key={item} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{item}</strong>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="grid-2">
        <div className="ops-panel">
          <div className="ops-table-toolbar">
            <div>
              <div className="ops-panel-title">PXE assignments</div>
              <p className="ops-subtle">Each assignment gives a specific MAC address a dedicated boot chain and answer file.</p>
            </div>
          </div>
          {assignments.length === 0 ? (
            <div className="ops-empty">No assignments yet. Add at least one assignment to move from shared boot menus to targeted bare-metal rollout.</div>
          ) : (
            <div className="ops-list">
              {assignments.map((assignment) => (
                <div key={assignment.id} className="ops-list-item">
                  <div className="ops-list-copy">
                    <strong>{assignment.hostname || assignment.mac_address}</strong>
                    <span>{assignment.mac_address} | {assignment.reserved_ip || 'DHCP dynamic'} | {assignment.profile?.name || 'No profile'} | {assignment.site_scope || 'no-site'}</span>
                  </div>
                  <div className="ops-list-metrics">
                    <span className="badge badge-light">{assignment.firmware_mode || 'uefi'}</span>
                    <span className="badge badge-info">{assignment.boot_once ? 'boot-once' : 'persistent'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Deployment services</div>
            <p className="ops-subtle">Preview the generated dnsmasq, nginx, and boot-host installer assets, then download the ready-to-apply PXE bundle.</p>
          </div>
          <div className="ops-actions">
            <button className="btn btn-sm" onClick={refreshServicePreview}>Refresh service preview</button>
            <button className="btn btn-primary" onClick={downloadDeploymentBundle}>Download PXE bundle</button>
          </div>
          </div>
          {!servicePreview ? (
            <div className="ops-empty">Service preview is unavailable right now.</div>
          ) : (
            <>
              <div className="ops-detail-grid">
                <div className="ops-detail-item">
                  <span>Published profiles</span>
                  <strong>{(servicePreview.published_profiles || []).length}</strong>
                </div>
                <div className="ops-detail-item">
                  <span>Published assignments</span>
                  <strong>{(servicePreview.assignments || []).length}</strong>
                </div>
                <div className="ops-detail-item">
                  <span>TFTP root</span>
                  <strong>{servicePreview.tftp_manifest?.tftp_root || '-'}</strong>
                </div>
              </div>
              <div className="grid-2">
                <div className="ops-command-card">
                  <div className="ops-side-label">Generated dnsmasq config</div>
                  <pre className="ops-console">{servicePreview.dnsmasq_config || '# No dnsmasq config generated'}</pre>
                </div>
                <div className="ops-command-card">
                  <div className="ops-side-label">Generated nginx config</div>
                  <pre className="ops-console">{servicePreview.nginx_config || '# No nginx config generated'}</pre>
                </div>
              </div>
              <div className="grid-2">
                <div className="ops-command-card">
                  <div className="ops-side-label">TFTP / HTTP boot manifest</div>
                  <pre className="ops-console">{JSON.stringify(servicePreview.tftp_manifest || {}, null, 2)}</pre>
                </div>
                <div className="ops-command-card">
                  <div className="ops-side-label">Boot-host installer script</div>
                  <pre className="ops-console">{servicePreview.boot_host_install_script || '# No install script generated'}</pre>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="ops-panel">
        <div className="ops-table-toolbar">
          <div>
            <div className="ops-panel-title">Provisioning center vs network boot workspace</div>
            <p className="ops-subtle">This compares the enrolled-host image workflow with the managed-relay bare-metal workflow now available in Patch-SecOps Solution.</p>
          </div>
        </div>
        <table className="table ops-table">
          <thead>
            <tr>
              <th>Area</th>
              <th>Current provisioning center</th>
              <th>Managed network boot</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Starting point</strong></td>
              <td>Requires an already-enrolled host with the Patch-SecOps Solution agent.</td>
              <td>Handles hosts before the agent exists by using relay-delivered DHCP/TFTP/HTTP boot with controller enrollment on first boot.</td>
            </tr>
            <tr>
              <td><strong>Main transport</strong></td>
              <td>Ops queue plus agent snapshot and restore APIs.</td>
              <td>Published iPXE and answer endpoints, relay-scoped bundles, dnsmasq/nginx validation, and boot-session telemetry.</td>
            </tr>
            <tr>
              <td><strong>Best fit</strong></td>
              <td>Golden image redeployments, branch refreshes, lab rebuilds, and disaster recovery for managed fleets.</td>
              <td>New device rollout, pre-agent rebuilds, site-by-site bare-metal installs, and standardized OS deployment.</td>
            </tr>
            <tr>
              <td><strong>Current truth</strong></td>
              <td>Production-ready now.</td>
              <td>Boot publication, per-host assignment, and boot-host deployment bundle installation are live now. Advanced boot telemetry remains the next infrastructure refinement step.</td>
            </tr>
          </tbody>
        </table>
        <div className="ops-detail-grid" style={{ marginTop: 16 }}>
          <div className="ops-detail-item">
            <span>Recommended use today</span>
            <strong>Use Provisioning Center for enrolled-host reimage work and Network Boot for bare-metal rollout, published boot artifacts, and dedicated PXE host deployment.</strong>
          </div>
          <div className="ops-detail-item">
            <span>Safe message to customers</span>
            <strong>Patch-SecOps Solution now provides stored-image provisioning plus published network-boot artifacts, host assignments, and a downloadable bundle that installs the PXE boot-host services for bare-metal rollout.</strong>
          </div>
        </div>
        <div className="ops-list" style={{ marginTop: 16 }}>
          {orderedHosts.slice(0, 4).map((host) => (
            <div key={host.id} className="ops-list-item">
              <div className="ops-list-copy">
                <strong>{host.hostname}</strong>
                <span>{host.ip} | {host.os || 'Unknown OS'}{host.site ? ` | ${host.site}` : ''}</span>
              </div>
              <div className="ops-list-metrics">
                <span className="badge badge-light">{host.site || 'no-site'}</span>
                <span className={`badge ${host.is_online ? 'badge-success' : 'badge-secondary'}`}>{host.is_online ? 'online' : 'offline'}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
