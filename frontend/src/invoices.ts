export interface InvoiceReason { layer: string; code: string }
export interface Counterfactual { would_pass_checks: boolean | null; remaining_reasons: string[] }
export interface Invoice {
  id: string; document_hash: string; state: string; reason: string | null;
  can_recheck?: boolean;
  vendor_id: string | null; proposal_id: string | null;
  extraction: { vendor_name: string; invoice_number: string; amount_eth: string; due_date: string | null } | null;
  checks: { first_stop: string | null; reasons: InvoiceReason[]; without_layer: Record<string, Counterfactual>;
    screening?: { classification: string; reason: string; latency_ms?: number; windows?: number;
      horizon?: {status: string; score?: number; version?: string};
      bastion?: {status: string; score?: number; version?: string} } | null } | null;
  latency_ms: number | null; created_at: string; provenance: 'invoice_intake';
  proposal_status: string | null; execution_mode: string | null;
  transaction_hash: string | null; explorer_url: string | null;
  events: { stage: string; reason: string | null; at: string }[];
}
export interface InvoiceSnapshot {
  items: Invoice[]; intake_enabled: boolean; automatic_execution_enabled: boolean;
  live_execution_enabled: boolean; execution_mode: string;
  horizon_bastion_enabled?: boolean; horizon_bastion_evaluated?: boolean;
  no_action: { count: number; reason: string; at: string } | null;
}
export interface InvoiceVendor {
  id: string; name: string; payout_address: string; maximum_wei: string; version: number; active: boolean;
}
export interface VendorUpdate {
  name: string; payout_address: string; maximum_eth: string; expected_version: number; active: boolean;
}
export interface InvoiceRedTeam {
  available: boolean; simulation_only: true;
  generated_cases?: { id: string; category: string; text: string; attack_note?: string }[];
  attempts: { id: string; category: string; first_stop: string | null;
    measurement_valid?: boolean; state?: string; reason?: string;
    reasons: InvoiceReason[]; without_layer: Record<string, Counterfactual> }[];
}
export function invoiceIsSimulated(invoice: Pick<Invoice, 'state' | 'proposal_status' | 'execution_mode'>): boolean {
  return [invoice.state, invoice.proposal_status, invoice.execution_mode].some(value => value?.toLowerCase() === 'simulated');
}
export function invoiceExplorer(invoice: Invoice): string | null {
  if (invoiceIsSimulated(invoice) || invoice.execution_mode !== 'sepolia' ||
      !/^0x[0-9a-fA-F]{64}$/.test(invoice.transaction_hash ?? '') || !invoice.explorer_url) return null;
  try {
    const url = new URL(invoice.explorer_url);
    return url.protocol === 'https:' && url.hostname === 'sepolia.etherscan.io' &&
      !url.port && !url.username && !url.password && !url.search && !url.hash &&
      url.pathname === `/tx/${invoice.transaction_hash}` ? url.href : null;
  } catch { return null; }
}
export function invoiceEventLabel(stage: string): string {
  const labels: Record<string, string> = { observed: 'Observed', extracted: 'Extracted', checked: 'Checked',
    paid: 'Paid · submitted, not confirmed', submitted: 'Paid · submitted, not confirmed',
    verified: 'Verified · matching receipt', simulated: 'SIMULATED · no broadcast' };
  return labels[stage.toLowerCase()] ?? stage;
}
export function counterfactualLabel(result: Counterfactual): string {
  return result.would_pass_checks === true ? 'Would pass checks' : result.would_pass_checks === false ? 'Would still stop' : 'Unknown';
}
export function redTeamCounts(report: InvoiceRedTeam) {
  const results = report.attempts.flatMap(attempt => Object.values(attempt.without_layer));
  return { attempts: report.attempts.length,
    stopped: report.attempts.filter(attempt => Boolean(attempt.first_stop)).length,
    wouldPass: results.filter(result => result.would_pass_checks === true).length,
    unknown: results.filter(result => result.would_pass_checks == null).length };
}

export function invoiceFileError(file: Pick<File, 'name' | 'size'>): string | null {
  if (!/\.(txt|pdf|eml)$/i.test(file.name)) return 'Choose a TXT, text-based PDF or EML invoice.';
  if (file.size > 1_000_000) return 'Choose a file smaller than 1 MB.';
  if (file.size === 0) return 'This file is empty. Choose another invoice.';
  return null;
}

export function invoiceReasonLabel(reason: string | null): string {
  const labels: Record<string, string> = {
    DOCUMENT_ADDRESS_MISMATCH: 'Payout address does not match the vendor.',
    DUPLICATE_INVOICE: 'This invoice has already been processed.',
    MISSING_OR_CONFLICTING_AMOUNT: 'The payment amount needs review.',
    MODEL_UNAVAILABLE_OR_INVALID: 'Extraction failed. Review this invoice.',
    EXACT_VENDOR_REQUIRED: 'Vendor does not match the approved registry.',
    RULES_MALICIOUS: 'Suspicious instructions detected.',
    NOT_BROADCAST: 'No funds sent.',
    LEARNED_ATTACK: 'Screening detected suspicious instructions.',
    LEARNED_REVIEW: 'Horizon and Bastion disagree. Review required.',
    LEARNED_ERROR: 'Screening unavailable or not validated. Review required.',
  };
  return reason ? labels[reason] ?? reason.replaceAll('_', ' ').toLowerCase() : '';
}
