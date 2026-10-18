import assert from 'node:assert/strict';
import test from 'node:test';
import { matchesProposalFilter, proposalFilters } from '../src/proposalFilters.ts';
import type { ProposalStatus } from '../src/types/index.ts';

test('every lifecycle state belongs to exactly one display group and remains visible in All', () => {
  const statuses: ProposalStatus[] = [
    'PROPOSED', 'EVALUATING', 'ALLOWED', 'ESCALATED', 'BLOCKED', 'APPROVED',
    'REJECTED', 'EXPIRED_APPROVAL', 'AUTHORIZED', 'SIGNING', 'SIGNED',
    'SUBMITTED', 'CONFIRMED', 'FAILED', 'SIGN_FAILED', 'TX_FAILED',
  ];
  for (const status of statuses) {
    assert.equal(matchesProposalFilter(status, 'ALL'), true);
    assert.equal(proposalFilters.filter(({ value }) =>
      value !== 'ALL' && matchesProposalFilter(status, value)).length, 1, status);
  }
});

test('ready to sign does not include pending approvals or intermediate execution states', () => {
  assert.equal(matchesProposalFilter('ALLOWED', 'READY'), true);
  assert.equal(matchesProposalFilter('APPROVED', 'READY'), true);
  for (const status of ['ESCALATED', 'AUTHORIZED', 'SIGNING', 'SIGNED'] as const) {
    assert.equal(matchesProposalFilter(status, 'READY'), false);
  }
  assert.equal(matchesProposalFilter('ESCALATED', 'APPROVAL'), true);
});

test('sent, blocked, and failed outcomes remain distinct', () => {
  assert.equal(matchesProposalFilter('SUBMITTED', 'SENT'), true);
  assert.equal(matchesProposalFilter('CONFIRMED', 'SENT'), true);
  assert.equal(matchesProposalFilter('REJECTED', 'BLOCKED'), true);
  assert.equal(matchesProposalFilter('EXPIRED_APPROVAL', 'BLOCKED'), true);
  assert.equal(matchesProposalFilter('TX_FAILED', 'FAILED'), true);
  assert.equal(matchesProposalFilter('FAILED', 'SENT'), false);
});
