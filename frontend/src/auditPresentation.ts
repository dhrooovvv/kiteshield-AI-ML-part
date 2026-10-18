export function humanizeEvent(value: string): string {
  return value.toLowerCase().replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

// Display only known audit metadata; raw prompt bodies and credentials stay out of the UI.
const visibleFields = new Set([
  'proposal_id', 'approval_id', 'policy_id', 'policy_version', 'version',
  'decision', 'reason_codes', 'reason_code', 'status', 'review_type',
  'amount_wei', 'recipient', 'chain_id', 'asset_type', 'daily_spent_wei',
  'action_digest', 'tx_hash', 'transaction_id', 'detector_versions',
]);

export function presentAuditDetails(details: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(details).filter(([key]) => visibleFields.has(key)));
}
