import { useSyncExternalStore } from 'react';
import { api } from './api/client.ts';
import type { CredentialRole } from './api/client.ts';

export function useConnectedRoles(): readonly CredentialRole[] {
  return useSyncExternalStore(
    api.subscribeCredentials, api.getConnectedRoles, api.getServerConnectedRoles,
  );
}

export function useRole(role: CredentialRole): boolean {
  const roles = useConnectedRoles();
  return roles.includes(role) || roles.includes('demoAdmin');
}
