import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

test('compact approval ledger separates executable approvals from informational holds', async () => {
  const server = await createServer({ configFile: false, appType: 'custom', server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { ApprovalsView } = await server.ssrLoadModule('/src/views/ApprovalsView.tsx');
    const props = { pendingApprovals: [], promptReviews: [{ id: 'review-1', correlation_id: 'full-correlation-reference', created_at: '2026-10-18T00:00:00Z' }], pendingApprovalsError: null, promptReviewsError: null, onSelectApproval: () => {}, onOpenAudit: () => {}, loading: false };
    const render = (overrides = {}) => renderToStaticMarkup(createElement(ApprovalsView, { ...props, ...overrides }));
    const held = render();
    assert.match(held, /approvals-workspace/);
    assert.match(held, /1 held/);
    assert.match(held, /full-correlation-reference/);
    assert.match(held, /View audit/);
    assert.match(held, /These holds cannot authorize a transaction/);
    assert.doesNotMatch(held, /Review &amp; Decide|Sign|Broadcast|glass-panel|queue-card/);
    const mixed = render({ pendingApprovals: [{ id: 'approval-1', action_digest: 'complete-action-digest', expires_at: '2026-10-19T00:00:00Z', proposal: { prompt: 'Synthetic payment', recipient: 'complete-recipient', amount_eth: '0.75' } }] });
    assert.match(mixed, /Transaction approvals/);
    assert.match(mixed, /Prompt-security reviews/);
    assert.match(mixed, /1 awaiting decision/);
    assert.match(mixed, /0.75 ETH/);
    assert.match(mixed, /complete-recipient/);
    assert.match(mixed, /complete-action-digest/);
    assert.equal((mixed.match(/Review &amp; Decide/g) || []).length, 1);
    const failed = render({ promptReviewsError: 'Connection unavailable' });
    assert.match(failed, /Connection unavailable/);
    assert.doesNotMatch(failed, /Queue clear|Detector disagreement/);
    assert.match(render({ promptReviews: [] }), /Queue clear/);
    assert.doesNotMatch(render({ promptReviews: [], loading: true }), /Queue clear/);
  } finally { await server.close(); }
});
