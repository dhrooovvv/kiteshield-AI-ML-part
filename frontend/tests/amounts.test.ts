import assert from 'node:assert/strict';
import test from 'node:test';
import { ethToWei, weiToEth } from '../src/amounts.ts';
import { api } from '../src/api/client.ts';

test('payment and policy amounts retain exact wei precision', () => {
  assert.equal(ethToWei('.03'), '30000000000000000');
  assert.equal(ethToWei('0.03'), ethToWei('.03'));
  assert.equal(ethToWei('1.123456789012345678'), '1123456789012345678');
  assert.equal(weiToEth('100000000000000001'), '0.100000000000000001');
  assert.equal(weiToEth('0'), '0');
});

test('ambiguous numeric formats are rejected rather than rounded', () => {
  for (const value of ['', '-.03', '0', '1e3', '1,000', 'NaN', '0.0000000000000000001']) {
    assert.throws(() => ethToWei(value), undefined, value);
  }
});

test('privileged operations never reuse the proposer credential or caller identity', async (context) => {
  api.setApiKey('test-proposer-key');
  api.setRoleKey('approver', 'test-approver-key');
  api.setRoleKey('policyAdmin', 'test-policy-key');
  const calls: { url: string; key: string; body: Record<string, unknown> }[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, key: (options.headers as Record<string, string>)['X-API-Key'],
      body: JSON.parse(options.body as string) });
    return Response.json({ data: {} });
  });
  try {
    await api.createPolicy({ max_amount_wei: '100' });
    await api.decideApproval('id', 'APPROVE');
    await api.proposeWithAgent('Explicit test prompt');
    assert.deepEqual(calls.map(call => call.key), ['test-policy-key', 'test-approver-key', 'test-proposer-key']);
    assert.deepEqual(calls[1].body, { decision: 'APPROVE' });
  } finally {
    api.setApiKey('');
    api.setRoleKey('approver', '');
    api.setRoleKey('policyAdmin', '');
  }
});
