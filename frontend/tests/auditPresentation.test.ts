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


test('compact audit rows retain evidence and exclude sensitive details', async () => {
  const { createServer } = await import('vite');
  const { createElement } = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { AuditEventList } = await server.ssrLoadModule('/src/components/AuditEventList.tsx');
    const html = renderToStaticMarkup(createElement(AuditEventList, { events: [{
      id: 'audit-fixture', correlation_id: 'request-fixture', event_type: 'TX_CONFIRMED',
      actor: 'receipt_reconciler', details: { proposal_id: 'proposal-fixture', api_key: 'omit-me', prompt: 'private-prompt' },
      previous_hash: 'a'.repeat(64), event_hash: 'b'.repeat(64),
      created_at: '2026-10-19T06:30:00Z', policy_version: 6,
    }] }));
    assert.match(html, /Tx confirmed/);
    assert.match(html, /proposal-fixture/);
    assert.match(html, /a{64}/);
    assert.match(html, /b{64}/);
    assert.match(html, /datetime="2026-10-19T06:30:00Z"/i);
    assert.doesNotMatch(html, /omit-me|private-prompt/);
    assert.doesNotMatch(html, /<details[^>]* open/);
  } finally { await server.close(); }
});
