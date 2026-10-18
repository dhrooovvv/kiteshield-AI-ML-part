import assert from 'node:assert/strict';
import test from 'node:test';
import { countEscalations, countHumanAttentionItems } from '../src/dashboardMetrics.ts';
import type { PromptReviewEvent } from '../src/types/index.ts';

const review = { status: 'REVIEW_REQUIRED' } as PromptReviewEvent;

test('counts transaction escalations and prompt reviews, not successful transactions', () => {
  const proposals = [
    { status: 'ESCALATED' },
    { status: 'ALLOWED' },
    { status: 'SUBMITTED' },
    { status: 'CONFIRMED' },
  ];

  assert.equal(countEscalations(proposals, [review]), 2);
});

test('refresh replacement does not accumulate stale local review counts', () => {
  const proposals = [{ status: 'ALLOWED' }];

  assert.equal(countEscalations(proposals, [review, review]), 2);
  assert.equal(countEscalations(proposals, [review]), 1);
});

test('human attention count combines transaction approvals and prompt reviews', () => {
  assert.equal(countHumanAttentionItems([{ id: 'approval-1' }, { id: 'approval-2' }], [review]), 3);
  assert.equal(countHumanAttentionItems([], []), 0);
});
