import React from 'react';

export function PatchManagerPage({ hosts, API, apiFetch, AppIcon, useInterval, PatchManagerOpsPage }) {
  return (
    <PatchManagerOpsPage
      hosts={hosts}
      API={API}
      apiFetch={apiFetch}
      AppIcon={AppIcon}
      useInterval={useInterval}
    />
  );
}
