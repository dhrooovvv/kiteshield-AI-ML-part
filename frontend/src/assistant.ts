import type { Proposal } from './types/index.ts';

export interface AssistantAnswer {
  kind: string; title: string; message?: string;
  data?: {
    [key: string]: unknown;
    task_id?: string; state?: string;
    draft_id?: string; proposal_id?: string | null; amount_eth?: string; recipient?: string;
    mode?: string; chain_id?: number; status?: string; message?: string;
    submitted_proposal?: Proposal;
    count?: number; total_eth?: string; period?: string; basis?: string;
    holdings?: { asset: string; address: string; role: string; balance: string }[];
    payments?: { proposal_id: string; recipient: string; amount_eth: string; status: string;
      recorded_at: string; explorer_url: string | null }[];
    items?: { proposal_id: string; expires_at: string }[];
    states?: Record<string, number>;
    choices?: { id: string; name: string; folder: string }[];
  };
}
export const assistantExamples = ['What is my current balance?', 'How much did I pay last month?',
  'What was my biggest payment?', 'How much budget is left?', 'Show pending approvals',
  'Find acme.pdf and pay it.', 'Pay all pending invoices from approved vendors.'];

export function contextualQuestion(text: string, previous?: { question: string; kind: string }): string {
  const period = text.trim().match(/^(?:and|what about)\s+(last month|this month|today|yesterday|last week|this week|last 30 days)[?.!]?$/i)?.[1];
  if (!period || previous?.kind !== 'payments' || !/^(?:how|what|show|list)\b/i.test(previous.question.trim())) return text;
  const base = previous.question.replace(/\b(?:last month|this month|today|yesterday|last week|this week|last 30 days|all time)\b/gi, '').replace(/[?.!]+$/, '').trim();
  return `${base} for ${period}?`;
}
export const assistantFactLabels: Record<string, string> = {
  period: 'Period', count: 'Payments', total_eth: 'Total ETH',
  recipient_filter: 'Recipient filter',
  daily_limit_eth: 'Daily budget · ETH', spent_today_eth: 'Spent today · ETH',
  pending_eth: 'Reserved · ETH', remaining_eth: 'Remaining · ETH', autonomous_cap_eth: 'Automation cap · ETH',
  escalation_threshold_eth: 'Approval threshold · ETH', absolute_max_eth: 'Maximum payment · ETH',
  policy_version: 'Policy version', date: 'UTC date', mode: 'Mode', state: 'State',
  target_balance_eth: 'Target · ETH', daily_actions_used: 'Actions today', cooldown_active: 'Cooldown active',
  observation_fresh: 'Fresh observation', expired_unresolved: 'Expired requests',
};
export function safeAssistantExplorer(url: string | null): string | null {
  return /^https:\/\/sepolia\.etherscan\.io\/tx\/0x[0-9a-fA-F]{64}$/.test(url ?? '') ? url : null;
}
