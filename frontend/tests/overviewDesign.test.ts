import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';

test('agent container retains the light theme without dark-panel overrides', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
  const panelRules = [...css.matchAll(/\.overview-page \.overview-workspace > \.agent-panel\s*\{([^}]+)\}/g)].map(match => match[1]).join('');
  assert.doesNotMatch(panelRules, /--bg-card:\s*#153c2d|color:\s*#ffffff/);
  assert.doesNotMatch(panelRules, /--text-main:|--bg-subtle:/);
  assert.match(css, /\.glass-panel\s*\{[^}]*background:\s*var\(--bg-card\) !important/);
});

test('overview restyle preserves real metrics, approval holds, and restricted proposal controls', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { OverviewView } = await server.ssrLoadModule('/src/views/OverviewView.tsx');
    const noop = () => {};
    const props = {
      proposals: ['ALLOWED', 'CONFIRMED', 'ESCALATED', 'BLOCKED'].map((status, index) => ({
        id: `proposal-${index}`, status, prompt: `Synthetic payment ${index}`, recipient: '0x' + '11'.repeat(20),
        amount_eth: '0.00002', updated_at: '2026-10-18T00:00:00Z', correlation_id: `test-${index}`,
      })), blockedAttemptsCount: 17,
      pendingApprovals: [{ id: 'pending-1' }], promptReviews: [{ id: 'review-1' }],
      activePolicy: { version: 6, max_amount_wei: '1000000000000000000',
        escalation_threshold_wei: '500000000000000000', daily_limit_wei: '5000000000000000000',
        allowed_recipients: ['0x' + '11'.repeat(20)] },
      onProposalCreated: noop, onPolicyUpdated: noop, onOpenAudit: noop, onOpenDetails: noop,
      onSelectApproval: noop, onNavigateToTab: noop,
    };
    const html = renderToStaticMarkup(createElement(OverviewView, props));
    for (const [tone, expected] of [['neutral', 4], ['allowed', 2], ['escalated', 2], ['blocked', 17]]) {
      assert.match(html, new RegExp(`overview-metric-${tone}[^]*?<strong>${expected}</strong>`));
    }
    assert.match(html, /overview-workspace/);
    assert.match(html, /Active Security Policy/);
    assert.match(html, /Recent Agent Activity/);
    assert.match(html, /Review Action/);
    assert.match(html, /View Queue \(1\)/);
    assert.match(html, /1 prompt security reviews/);
    assert.match(html, /require human approval before execution/);
    assert.match(html, /Proposer required/);
    assert.match(html, /disabled=""/);
    assert.doesNotMatch(html, /linear-gradient|Private keys locked|7,265|11.01%/);
  } finally { await server.close(); }
});
