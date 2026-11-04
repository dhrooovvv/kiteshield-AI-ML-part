import { api, type CredentialRole } from './api/client.ts';
import type { VaultStatus } from './vault.ts';

export interface AutonomyStep { position: number; tool: string; state: string; result: string | null }
export interface AutonomyEvent { id: number; kind: string; detail: string }
export interface AutonomyTask {
  id: string; amount: number; state: string; reason: string | null;
  payment_cap: number; funding_cap: number | string; steps: AutonomyStep[]; events: AutonomyEvent[];
  payment_backend?: 'NATIVE' | 'VAULT';
}
export interface AutonomySnapshot {
  mode: string; tasks: AutonomyTask[];
  wallet_source?: string;
  system_events?: AutonomyEvent[];
  mandate?: {version: number; supplier: string; recipient: string; payment_cap: number; funding_cap: string} | null;
  issues: { id: string; task_id: string | null; reason: string; resolved: number }[];
  control: { quarantined: number; epoch: number };
}
export interface AutonomyWallet {
  mode: string; address: string; balance_wei: string; payments_enabled: boolean;
  faucet_enabled: boolean; recipient: string | null; max_payment_fee_wei: string;
  wallet_source?: string; supplier?: string; policy_managed?: boolean;
  approval_threshold_wei?: string; vendor_maximum_wei?: string;
  incoming_watch?: {enabled: boolean; block?: number | null; failures?: number; suspended_epoch?: number | null};
  vault?: VaultStatus;
  new_task_backend?: 'NATIVE' | 'VAULT';
}
const base = (import.meta.env?.VITE_API_BASE_URL || '/api/v1') + '/autonomy';
export const readableReason = (value: string): string => value.toLowerCase().replaceAll('_', ' ');
export function canRunAutonomy(mode: string, roles: readonly string[]): boolean {
  return ['SIMULATED', 'SEPOLIA'].includes(mode) && roles.includes('proposer');
}
export async function autonomyAvailable(): Promise<boolean> {
  try {
    const response = await fetch(base + '/health', {cache: 'no-store', signal: AbortSignal.timeout(5000)});
    if (!response.ok) return false;
    const result = await response.json();
    return result.enabled === true && ['SIMULATED', 'SEPOLIA'].includes(result.mode);
  } catch { return false; }
}
export async function autonomyRequest<T>(path: string, role: CredentialRole = 'proposer',
  body?: unknown, method?: string): Promise<T> {
  if (!api.getConnectedRoles().includes(role)) throw new Error(`Connect the ${role} role using API key first.`);
  const response = await fetch(base + path, {
    method: method || (body === undefined ? 'GET' : 'POST'), cache: 'no-store',
    signal: AbortSignal.timeout(15000),
    headers: {'Content-Type': 'application/json', 'X-API-Key': api.getRoleKey(role)},
    ...(body === undefined ? {} : {body: JSON.stringify(body)}),
  });
  let result;
  try { result = await response.json(); }
  catch { throw new Error('Task status unavailable. Check task history before retrying.'); }
  if (!response.ok) throw new Error(typeof result.detail === 'string'
    ? readableReason(result.detail) : 'The request was rejected. Check your role and input.');
  return result as T;
}

export interface PendingGoal { goal: string; key: string }
export function goalSubmission(previous: PendingGoal | null, goal: string,
  makeKey: () => string = () => crypto.randomUUID()): PendingGoal {
  return previous?.goal === goal ? previous : {goal, key: makeKey()};
}

export function autonomyStepState(taskState: string, stepState = 'NOT_STARTED'): string {
  if (stepState === 'COMPLETED') return stepState;
  if (['REJECTED', 'CANCELLED', 'FAILED'].includes(taskState)) return 'NOT_EXECUTED';
  if (taskState === 'HUMAN_REQUIRED') return 'ON_HOLD';
  return stepState;
}

export function transactionLinks(task: AutonomyTask): {hash: string; url: string}[] {
  const links = new Map<string, string>();
  for (const encoded of [...task.steps.map(step => step.result),
    ...task.events.filter(event => event.kind === 'TRANSACTION_OBSERVED').map(event => event.detail)]) {
    try {
      const result = JSON.parse(encoded || '{}');
      if (result.mode === 'SEPOLIA' && /^0x[0-9a-fA-F]{64}$/.test(result.tx_hash)) {
        links.set(result.tx_hash, `https://sepolia.etherscan.io/tx/${result.tx_hash}`);
      }
    } catch { /* An unreadable result is never transaction evidence. */ }
  }
  return Array.from(links, ([hash, url]) => ({hash, url}));
}
