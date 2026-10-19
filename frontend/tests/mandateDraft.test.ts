import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { api } from '../src/api/client.ts';

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

test('draft form application is separate from existing saving and execute confirmation', () => {
  const box = readFileSync('src/components/MandateDraftBox.tsx', 'utf8');
  const helper = readFileSync('src/mandateDraft.ts', 'utf8');
  assert.match(box, /Apply draft to form · not saved/);
  assert.doesNotMatch(box + helper, /saveTreasury|setTreasuryMode|observeTreasury|\.submit\(/);
  assert.match(helper, /value === null \? ''/);
});
