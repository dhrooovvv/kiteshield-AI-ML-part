export interface TreasuryConfig {
  sender: string; recipient: string; chain_id: 11155111;
  target_balance_wei: string; sweep_maximum_wei: string; minimum_excess_wei: string;
  cooldown_seconds: number; daily_action_limit: number; freshness_seconds: number;
}
export interface TreasuryPlan {
  state: string; reason: string; available_excess_wei: string; proposed_amount_wei: string;
}
export interface TreasuryObservation {
  status: 'available' | 'unavailable'; reason?: string; observed_at: string;
  balance_wei?: string; maximum_fee_reserve_wei?: string; fee_error?: string;
  block_number?: number; block_hash?: string; block_time?: string; simulation?: boolean;
}
export interface TreasuryStatus {
  mode: 'off' | 'plan_only' | 'execute'; sender: string;
  mandate: (TreasuryConfig & { id: string; version: number; enabled: boolean }) | null;
  observation: TreasuryObservation | null; plan: TreasuryPlan | null;
  observation_fresh: boolean; daily_actions_used: number; cooldown_active: boolean;
  execution: { available: boolean; reason: string | null; monitor_enabled: boolean;
    execution_mode: 'simulated' | 'sepolia'; integration: string };
}
export interface TreasuryAction {
  id: string; mandate_version: number; state: string; reason: string; created_at: string;
  proposal_id: string | null; plan: TreasuryPlan; observation: TreasuryObservation;
  tx_hash: string | null; explorer_url: string | null; execution_status: string | null;
  proposal_status: string | null; simulation: boolean; initiated_at: string | null;
}

/** UI guidance only. Backend authorization independently enforces every gate. */
export function treasuryExecuteBlockers(status: TreasuryStatus, admin: boolean, at = Date.now()): string[] {
  const reasons: string[] = [];
  if (!status.mandate) reasons.push('Configure a mandate before activating execution.');
  if (!admin) reasons.push('Connect a Policy administrator credential to activate execution.');
  if (!status.execution.available) {
    reasons.push(status.execution.reason === 'MONITOR_DISABLED'
      ? 'The monitor is disabled. Restart the backend after setting TREASURY_MONITOR_ENABLED=true.'
      : status.execution.reason === 'GLOBAL_AUTOMATION_DISABLED'
        ? 'Global autonomous execution is disabled in the backend.'
        : 'Execution requires verified live Sepolia mode.');
  }
  if (status.mode === 'off') reasons.push('Save a mandate, then enable plan-only first.');
  if (status.mode === 'execute') reasons.push('Execute mode is already active.');
  const observed = Date.parse(status.observation?.observed_at ?? '');
  const blockTime = Date.parse(status.observation?.block_time ?? '');
  const maxAge = (status.mandate?.freshness_seconds ?? 60) * 1000;
  if (!status.observation_fresh || !Number.isFinite(observed) || !Number.isFinite(blockTime)
    || at - observed < 0 || at - observed > maxAge || at - blockTime < -15000 || at - blockTime > maxAge) {
    reasons.push('Click Observe once to get a fresh balance and fee estimate.');
  }
  if (status.plan?.state !== 'ELIGIBLE') reasons.push(status.plan?.reason === 'EXCESS_BELOW_MINIMUM'
    ? 'There is not enough excess above the target after fees. Review the target balance; no sweep is eligible.'
    : `No eligible sweep: ${status.plan?.reason.replaceAll('_', ' ').toLowerCase() ?? 'observe in plan-only mode first'}.`);
  return reasons;
}
