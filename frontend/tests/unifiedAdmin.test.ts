import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from '../src/api/client.ts';

test('one verified Admin key supplies all human actions and disconnect clears access', async context => {
  api.disconnect();
  const seen: string[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal((options.headers as Record<string, string>)['X-API-Key'], 'human-admin-key');
    if (url.endsWith('/security/identity')) return Response.json({ data: { role: 'administrator' } });
    seen.push(url);
    return Response.json({ data: {} });
  });
  try {
    await api.connect('human-admin-key');
    assert.deepEqual(api.getConnectedRoles(), ['admin', 'proposer', 'approver', 'policyAdmin']);
    await api.proposeWithAgent('pay approved supplier');
    await api.decideApproval('approval', 'APPROVE');
    await api.createPolicy({ max_amount_wei: '1' });
    assert.equal(seen.length, 3);
    api.disconnect();
    assert.deepEqual(api.getConnectedRoles(), []);
    for (const role of ['admin', 'proposer', 'approver', 'policyAdmin'] as const) {
      assert.equal(api.getRoleKey(role), '');
    }
  } finally { api.disconnect(); }
});

test('disconnect while verification is pending prevents stale authentication', async context => {
  api.disconnect();
  let complete: (response: Response) => void = () => {};
  context.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => { complete = resolve; }));
  const connection = api.connect('pending-key');
  api.disconnect();
  complete(Response.json({ data: { role: 'administrator' } }));
  await connection;
  assert.deepEqual(api.getConnectedRoles(), []);
  assert.equal(api.getRoleKey('admin'), '');
});

test('revoked Admin credential clears all effective permissions', async context => {
  api.disconnect();
  context.mock.method(globalThis, 'fetch', async (url: string) => url.endsWith('/security/identity')
    ? Response.json({ data: { role: 'administrator' } })
    : Response.json({ detail: { code: 'INVALID_API_KEY' } }, { status: 401 }));
  try {
    await api.connect('revoked-key');
    await assert.rejects(() => api.decideApproval('approval', 'APPROVE'));
    assert.deepEqual(api.getConnectedRoles(), []);
    assert.equal(api.getRoleKey('policyAdmin'), '');
  } finally { api.disconnect(); }
});
