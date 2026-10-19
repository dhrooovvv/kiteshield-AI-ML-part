import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { api } from '../src/api/client.ts';
import { treasuryExecuteBlockers } from '../src/treasury.ts';
import type { TreasuryStatus } from '../src/treasury.ts';

test('execute readiness explains monitor, excess, roles and stale observations without granting authority', () => {
  const at = Date.parse('2026-10-19T07:00:00Z');
  const state = {
    mode: 'plan_only', mandate: { freshness_seconds: 60 },
    observation: { observed_at: new Date(at - 5000).toISOString(), block_time: new Date(at - 10000).toISOString() },
    observation_fresh: true, execution: { available: true },
    plan: { state: 'ELIGIBLE', reason: 'BOUNDED_SWEEP' },
  } as TreasuryStatus;
  assert.deepEqual(treasuryExecuteBlockers(state, true, at), []);
  assert.match(treasuryExecuteBlockers(state, false, at).join(), /Policy administrator/);
  assert.match(treasuryExecuteBlockers(state, true, at + 61000).join(), /fresh balance/);
  const blocked = { ...state, execution: { ...state.execution, available: false, reason: 'MONITOR_DISABLED' }, plan: { ...state.plan!, state: 'WITHIN_TARGET_BAND', reason: 'EXCESS_BELOW_MINIMUM' } };
  const reasons = treasuryExecuteBlockers(blocked, true, at).join();
  assert.match(reasons, /TREASURY_MONITOR_ENABLED=true/);
  assert.match(reasons, /not enough excess/);
  assert.match(treasuryExecuteBlockers({ ...state, observation: null }, true, at).join(), /fresh balance/);
});

test('treasury refresh only reads; writes use policy administrator credentials', async context => {
  const calls: { url: string; options: RequestInit }[] = [];
  api.setApiKey('synthetic-proposer');
  api.setRoleKey('policyAdmin', 'synthetic-policy-admin');
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, options }); return Response.json({ data: {} });
  });
  try {
    await api.getTreasury(); await api.getTreasuryActions();
    assert.ok(calls.every(c => (c.options.method ?? 'GET') === 'GET'));
    await api.observeTreasury(); await api.setTreasuryMode('execute', 3, true);
    for (const call of calls.slice(2)) {
      assert.equal((call.options.headers as Record<string, string>)['X-API-Key'], 'synthetic-policy-admin');
      assert.equal(call.options.method, 'POST');
    }
    assert.deepEqual(JSON.parse(calls[3].options.body as string), { mode: 'execute', expected_version: 3, confirm_standing_permission: true });
  } finally { api.setApiKey(''); api.setRoleKey('policyAdmin', ''); }
});

test('treasury displays exact state, refill-only alert, stale and simulated evidence honestly', async () => {
  const server = await createServer({ configFile: false, appType: 'custom', server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { TreasurySummary, TreasuryView } = await server.ssrLoadModule('/src/views/TreasuryView.tsx');
    const state = {
      mode: 'plan_only', sender: '0x' + '11'.repeat(20), mandate: null,
      observation: { status: 'unavailable', reason: 'WRONG_CHAIN', observed_at: '2026-10-19T00:00:00Z', simulation: true },
      observation_fresh: false, daily_actions_used: 2, cooldown_active: true,
      execution: { available: false, reason: 'LIVE_SEPOLIA_REQUIRED', execution_mode: 'simulated' },
      plan: { state: 'BELOW_TARGET', reason: 'HUMAN_REFILL_ONLY', proposed_amount_wei: '0' },
    };
    const html = renderToStaticMarkup(createElement(TreasurySummary, { status: state }));
    for (const phrase of ['Plan-only', 'Human refill required', 'cannot refill', 'WRONG_CHAIN', 'Stale / unavailable', 'not executed', 'no on-chain execution']) assert.ok(html.includes(phrase), phrase);
    assert.doesNotMatch(html, /etherscan.io\/tx|Sign|Confirmed|executed successfully/);
    assert.match(renderToStaticMarkup(createElement(TreasuryView, { refreshRevision: 0, onOpenAudit: () => {}, onOpenDetails: () => {} })), /Reload treasury status/);
  } finally { await server.close(); }
});

test('two-card treasury dashboard highlights eligibility without calling a proposal a confirmed payment', async () => {
  const server = await createServer({ configFile: false, appType: 'custom', server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { TreasurySummary, TreasuryActivity } = await server.ssrLoadModule('/src/views/TreasuryView.tsx');
    const status = {
      mode: 'execute', sender: '0x' + '11'.repeat(20),
      mandate: { version: 3, recipient: '0x' + '22'.repeat(20), target_balance_wei: '49869999995135800', sweep_maximum_wei: '30000000000000', minimum_excess_wei: '20000000000000', cooldown_seconds: 600, daily_action_limit: 3 },
      execution: { available: true }, observation_fresh: true, cooldown_active: false, daily_actions_used: 0,
      observation: { status: 'available', balance_wei: '49909999995135800', maximum_fee_reserve_wei: '781200', block_number: 123, observed_at: '2026-10-19T07:00:00Z' },
      plan: { state: 'ELIGIBLE', reason: 'BOUNDED_SWEEP', proposed_amount_wei: '30000000000000' },
    };
    const html = renderToStaticMarkup(createElement(TreasurySummary, { status }, createElement('button', {}, 'Synthetic configuration control')));
    assert.match(html, /treasury-dashboard-grid/);
    assert.ok(html.indexOf('Synthetic configuration control') < html.indexOf('treasury-eligibility'));
    for (const label of ['Mandate configuration', 'Sweep eligibility', 'Execution enabled · monitoring active', 'Eligible sweep · not executed', '0.00003 ETH', '0.0498699999951358 ETH', 'Only a matching receipt confirms payment']) assert.ok(html.includes(label), label);
    assert.doesNotMatch(html, /payment succeeded|CONFIRMED|etherscan.io\/tx/);
    const compact = renderToStaticMarkup(createElement(TreasurySummary, { status,
      activity: createElement('section', { className: 'treasury-actions' }, 'Synthetic activity'),
    }));
    assert.match(compact, /treasury-eligibility[^]*?Synthetic activity[^]*?<\/section><\/div>$/);
    const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
    assert.match(css, /grid-template-areas: 'configuration eligibility' 'activity eligibility'/);
    assert.match(css, /grid-template-areas: 'configuration' 'eligibility' 'activity'/);
    const workspace = css.match(/\.treasury-dashboard-grid\s*\{([^}]+)\}/)?.[1] ?? '';
    assert.match(workspace, /gap: 0/);
    assert.match(workspace, /border-radius: 20px/);
    assert.match(workspace, /overflow: hidden/);
    assert.match(css, /\.treasury-configuration, \.treasury-eligibility, \.treasury-actions\s*\{[^}]*border: 0; border-radius: 0/);
    const simulated = renderToStaticMarkup(createElement(TreasurySummary, { status, latestAction: { simulation: true, explorer_url: 'https://sepolia.etherscan.io/tx/fake' } }));
    assert.match(simulated, /Simulated · not broadcast/);
    assert.doesNotMatch(simulated, /href="https:\/\/sepolia.etherscan.io\/tx/);
    const stale = renderToStaticMarkup(createElement(TreasurySummary, { status: { ...status, observation_fresh: false } }));
    assert.doesNotMatch(stale, /Eligible sweep · not executed/);
    const actions = Array.from({ length: 5 }, (_, i) => ({ id: `action-${i}`, state: 'WITHIN_TARGET_BAND', reason: 'EXCESS_BELOW_MINIMUM', mandate_version: 3, observation: { block_number: i }, created_at: '2026-10-19T07:00:00Z' }));
    const history = renderToStaticMarkup(createElement(TreasuryActivity, { actions, onOpenAudit: () => {} }));
    assert.match(history, /Earlier activities \(4\)/);
    assert.equal((history.match(/View audit/g) ?? []).length, 1);
    const expanded = renderToStaticMarkup(createElement(TreasuryActivity, { actions: actions.slice(1), showAll: true, onOpenAudit: () => {} }));
    assert.equal((expanded.match(/View audit/g) ?? []).length, 4);
    assert.doesNotMatch(expanded, /Earlier activities/);
    assert.doesNotMatch(history, /<details[^>]* open/);
  } finally { await server.close(); }
});
