import { api } from './api/client.ts';
import type { TreasuryConfig, TreasuryStatus } from './treasury.ts';

/** Explicit operator action only. Never requests execute mode or retries a write. */
export async function previewTreasury(status: TreasuryStatus): Promise<TreasuryStatus> {
  if (!status.mandate) throw new Error('Configure a mandate before previewing.');
  if (status.mode === 'off') {
    await api.setTreasuryMode('plan_only', status.mandate.version);
  }
  // The existing observation endpoint forces plan-only even in execute mode.
  return api.observeTreasury();
}

export async function saveAndPreviewTreasury(
  config: TreasuryConfig, version: number, onSaved: (status: TreasuryStatus) => void,
): Promise<TreasuryStatus> {
  const saved = await api.saveTreasury(config, version);
  onSaved(saved);
  try {
    return await previewTreasury(saved);
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Preview unavailable';
    throw new Error(`Mandate saved, but preview did not complete. Execution was not enabled. ${reason} Use Refresh preview to retry without saving again.`);
  }
}
