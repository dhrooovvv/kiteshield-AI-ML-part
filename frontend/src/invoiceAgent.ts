export interface InvoiceAgentTask {
  task_id: string; state: string; stage: string; mode: 'simulated' | 'sepolia';
  reason: string | null; cancel_requested: boolean; can_cancel: boolean; created_at: string;
  items: { filename: string; invoice_id: string | null; state: string; reason: string | null;
    proposal_id: string | null; explorer_url: string | null; amount_eth: string | null; vendor_name: string | null }[];
}
export function taskStage(task: InvoiceAgentTask): string {
  if (task.state === 'CANCELLED') return 'Unsent work stopped';
  if (task.state === 'NEEDS_ATTENTION' || task.state === 'FAILED') return 'Needs attention';
  if (task.state === 'COMPLETED') return 'Task finished';
  return ({ QUEUED: 'Queued', PROCESSING_INVOICE: 'Processing invoice', SCREENING: 'Horizon + Bastion screening',
    EXTRACTING: 'Reading invoice', VALIDATING: 'Checking vendor and policy', EXECUTION_CHECK: 'Checking execution permission',
    RESULT_RECORDED: 'Recording result' } as Record<string, string>)[task.stage] ?? 'Processing';
}
export function taskFinished(task: InvoiceAgentTask): boolean {
  return ['COMPLETED', 'NEEDS_ATTENTION', 'CANCELLED', 'FAILED'].includes(task.state);
}
export function invoiceOutcome(state: string): string {
  return ({ SIMULATED: 'Simulated · no funds sent', VERIFIED: 'Receipt confirmed', PAID: 'Submitted · awaiting receipt',
    CHECKED: 'Checked · not executed', BLOCKED: 'Blocked', NEEDS_HUMAN_REVIEW: 'Needs review', UNCERTAIN: 'Outcome uncertain',
    REVERTED: 'Reverted' } as Record<string, string>)[state] ?? 'Processing';
}

export function invoiceAutomationDisabled(task: InvoiceAgentTask): boolean {
  // Task reasons are historical; reconciliation can advance an invoice afterward.
  return task.reason === 'AUTOMATION_DISABLED' && task.items.some(item => item.state === 'CHECKED');
}
