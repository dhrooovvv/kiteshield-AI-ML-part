import { api, type CredentialRole } from './api/client.ts';

export interface VaultStatus {
  enabled: boolean; payments_enabled: boolean; deployed?: boolean; configured?: boolean;
  owner?: string; agent?: string; recipient?: string; address?: string; epoch?: number; revision?: number;
  chain?: { remaining: string; perPayment: string; balance: string; agent_balance: string;
    expires: number; paused: boolean; epoch: number };
  operations?: { id: string; kind: string; status: string; tx_hash: string | null }[];
}

export function vaultReady(status: VaultStatus | undefined, now = Date.now()): boolean {
  return !!(status?.enabled && status.payments_enabled && status.configured && status.chain
    && !status.chain.paused && status.chain.expires * 1000 > now
    && status.chain.epoch === status.epoch && BigInt(status.chain.remaining) > 0n
    && BigInt(status.chain.balance) > 0n && BigInt(status.chain.agent_balance) > 0n);
}

export async function vaultRequest<T>(path: string, role: CredentialRole, body: unknown): Promise<T> {
  if (!api.getConnectedRoles().includes(role)) throw new Error(`Connect the ${role} role first.`);
  const response = await fetch((import.meta.env?.VITE_API_BASE_URL || '/api/v1') + '/vault' + path, {
    method: 'POST', cache: 'no-store', signal: AbortSignal.timeout(15000),
    headers: {'Content-Type': 'application/json', 'X-API-Key': api.getRoleKey(role)},
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || result.detail?.message || 'Vault action was blocked. Check its saved operation before retrying.');
  return result.data as T;
}
