import type { ProposalStatus } from './types/index.ts';

// Display groups only: these never change lifecycle states or action eligibility.
export const proposalFilters = [
  { value: 'ALL', label: 'All proposals' },
  { value: 'PENDING', label: 'In progress' },
  { value: 'APPROVAL', label: 'Needs approval' },
  { value: 'READY', label: 'Ready to sign' },
  { value: 'SENT', label: 'Sent' },
  { value: 'BLOCKED', label: 'Blocked / rejected' },
  { value: 'FAILED', label: 'Failed' },
] as const;

export type ProposalFilter = typeof proposalFilters[number]['value'];

const statusGroups: Record<ProposalStatus, Exclude<ProposalFilter, 'ALL'>> = {
  PROPOSED: 'PENDING',
  EVALUATING: 'PENDING',
  AUTHORIZED: 'PENDING',
  SIGNING: 'PENDING',
  SIGNED: 'PENDING',
  ESCALATED: 'APPROVAL',
  ALLOWED: 'READY',
  APPROVED: 'READY',
  SUBMITTED: 'SENT',
  CONFIRMED: 'SENT',
  BLOCKED: 'BLOCKED',
  REJECTED: 'BLOCKED',
  EXPIRED_APPROVAL: 'BLOCKED',
  FAILED: 'FAILED',
  SIGN_FAILED: 'FAILED',
  TX_FAILED: 'FAILED',
};

export function matchesProposalFilter(status: ProposalStatus, filter: ProposalFilter): boolean {
  return filter === 'ALL' || statusGroups[status] === filter;
}
