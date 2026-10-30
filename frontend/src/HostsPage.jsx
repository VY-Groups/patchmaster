import React from 'react';

export function HostsPage({ hosts, setHosts, API, apiFetch, hasRole, AppIcon, useInterval, HostsOpsPage }) {
  return (
    <HostsOpsPage
      hosts={hosts}
      setHosts={setHosts}
      API={API}
      apiFetch={apiFetch}
      hasRole={hasRole}
      AppIcon={AppIcon}
      useInterval={useInterval}
    />
  );
}
