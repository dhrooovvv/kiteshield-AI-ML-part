import type { Proposal, PromptReviewEvent } from './types/index.ts';

export function countEscalations(
  proposals: Pick<Proposal, 'status'>[],
  promptReviews: PromptReviewEvent[],
): number {
  return proposals.filter((proposal) => proposal.status === 'ESCALATED').length + promptReviews.length;
}

export function countHumanAttentionItems(
  pendingApprovals: unknown[],
  promptReviews: PromptReviewEvent[],
): number {
  return pendingApprovals.length + promptReviews.length;
}
