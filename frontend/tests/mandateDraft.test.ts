import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { api } from '../src/api/client.ts';
import { mandateDraftFields } from '../src/mandateDraft.ts';
import type { MandateDraftResult } from '../src/mandateDraft.ts';

test('draft endpoint uses administrator credential and never saves or activates', async context => {
  const calls: { url: string; options: RequestInit }[] = [];
  api.setRoleKey('policyAdmin', 'test-draft-admin');
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, options }); return Response.json({ data: { status: 'clarification' } });
  });
  try {
    await api.draftTreasuryMandate('Keep 0.04 ETH available.');
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/treasury\/draft$/);
    assert.equal(calls[0].options.method, 'POST');
    assert.equal((calls[0].options.headers as Record<string,string>)['X-API-Key'], 'test-draft-admin');
    assert.deepEqual(JSON.parse(calls[0].options.body as string), { instruction: 'Keep 0.04 ETH available.' });
  } finally { api.setRoleKey('policyAdmin', ''); }
});

test('draft fills editable state without saving or executing', () => {
  const box = readFileSync('src/components/MandateDraftBox.tsx', 'utf8');
  const helper = readFileSync('src/mandateDraft.ts', 'utf8');
  assert.match(box, /Use these values/);
  assert.match(box, /onApply\(result\)/);
  assert.match(box, /Nothing has been saved or enabled/);
  assert.doesNotMatch(box + helper, /saveTreasury|setTreasuryMode|observeTreasury|\.submit\(/);
  assert.match(helper, /value === null \? ''/);
});

test('validated draft maps all seven fields exactly; partial limits clear old values', () => {
  const result: MandateDraftResult = {
    status: 'draft', source: 'parser', resolved_recipient: '0x' + '22'.repeat(20),
    draft: { target_balance_eth: '0.04983', recipient_alias: 'treasury', max_actions_per_day: 3,
      sweep_maximum_eth: '0.00003', minimum_excess_eth: '0.00002', cooldown_seconds: 600,
      freshness_seconds: 60, unresolved_questions: [] }, validation: [], questions: [], warnings: [],
  };
  assert.deepEqual(mandateDraftFields(result), { recipient: result.resolved_recipient,
    target: '0.04983', daily: '3', maximum: '0.00003', minimum: '0.00002', cooldown: '600', freshness: '60' });
  assert.equal(mandateDraftFields({ ...result, draft: { ...result.draft!, cooldown_seconds: null } })?.cooldown, '');
  for (const status of ['invalid', 'refused', 'clarification'] as const) assert.equal(mandateDraftFields({ ...result, status }), null);
  assert.equal(mandateDraftFields({ ...result, resolved_recipient: null }), null);
  const view = readFileSync('src/views/TreasuryView.tsx', 'utf8');
  assert.match(view, /if \(values\) setFormValues\(values\)/);
  assert.doesNotMatch(view, /defaultValue=/);
});
