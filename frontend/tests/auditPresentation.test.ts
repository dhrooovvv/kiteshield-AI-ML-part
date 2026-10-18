import assert from 'node:assert/strict';
import test from 'node:test';
import { humanizeEvent, presentAuditDetails } from '../src/auditPresentation.ts';

test('audit labels are readable without changing API event codes', () => {
  assert.equal(humanizeEvent('PROMPT_SCREENING_REVIEW_REQUIRED'), 'Prompt screening review required');
});

test('audit display includes policy metadata but omits raw prompts and credentials', () => {
  assert.deepEqual(presentAuditDetails({ decision: 'ALLOW', amount_wei: '100', prompt: 'private body', api_key: 'test-only', signer_private_key: 'test-only' }), { decision: 'ALLOW', amount_wei: '100' });
});

test('audit presentation handles empty details', () => {
  assert.deepEqual(presentAuditDetails({}), {});
});
