import assert from 'node:assert/strict';
import test from 'node:test';
import { api, KiteShieldAPIError } from '../src/api/client.ts';

function clear() {
  api.setApiKey('');
  api.setRoleKey('approver', '');
  api.setRoleKey('policyAdmin', '');
  api.setRoleKey('demoAdmin', '');
}

test('typed or programmatically saved credentials do not imply verified roles', () => {
  clear();
  api.setApiKey('unverified-key');
  api.setRoleKey('approver', 'unverified-human');
  assert.deepEqual(api.getConnectedRoles(), []);
  clear();
});

test('only backend identity can connect the matching role; multiple roles stay connected', async (context) => {
  clear();
  context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
    const key = (options.headers as Record<string, string>)['X-API-Key'];
    const role = key === 'human-key' ? 'human_approver' : key === 'admin-key' ? 'policy_administrator' : 'proposer';
    return Response.json({ data: { role } });
  });
  let updates = 0;
  const unsubscribe = api.subscribeCredentials(() => { updates++; });
  try {
    await api.verifyAndSaveRoleKey('proposer', 'proposer-key');
    await api.verifyAndSaveRoleKey('approver', 'human-key');
    await api.verifyAndSaveRoleKey('policyAdmin', 'admin-key');
    assert.deepEqual(api.getConnectedRoles(), ['proposer', 'approver', 'policyAdmin']);
    assert.equal(updates, 3);
    await assert.rejects(() => api.verifyAndSaveRoleKey('policyAdmin', 'proposer-key'),
      (error: unknown) => error instanceof KiteShieldAPIError && error.code === 'CREDENTIAL_ROLE_MISMATCH');
    assert.equal(api.getRoleKey('policyAdmin'), 'admin-key');
    assert.deepEqual(api.getConnectedRoles(), ['proposer', 'approver', 'policyAdmin']);
  } finally { unsubscribe(); clear(); }
});

test('401 invalidates only the verified role whose credential failed', async (context) => {
  clear();
  let revoked = false;
  context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
    const key = (options.headers as Record<string, string>)['X-API-Key'];
    if (revoked && key === 'human-key') {
      return Response.json({ detail: { code: 'INVALID_API_KEY', message: 'Invalid API key' } }, { status: 401 });
    }
    return Response.json({ data: { role: key === 'human-key' ? 'human_approver' : 'proposer' } });
  });
  try {
    await api.verifyAndSaveRoleKey('proposer', 'proposer-key');
    await api.verifyAndSaveRoleKey('approver', 'human-key');
    revoked = true;
    await assert.rejects(() => api.decideApproval('test', 'APPROVE'));
    assert.deepEqual(api.getConnectedRoles(), ['proposer']);
    assert.equal(api.getRoleKey('approver'), '');
  } finally { clear(); }
});

test('a human-only connection can read data but never supplies a proposer mutation credential', async (context) => {
  clear();
  const requests: { method: string; key: string }[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    if (url.endsWith('/security/identity')) return Response.json({ data: { role: 'human_approver' } });
    requests.push({ method: options.method ?? 'GET',
      key: (options.headers as Record<string, string>)['X-API-Key'] });
    return Response.json({ data: [] });
  });
  try {
    await api.verifyAndSaveRoleKey('approver', 'human-key');
    await api.listPolicies();
    await api.proposeWithAgent('test');
    assert.deepEqual(requests, [{ method: 'GET', key: 'human-key' }, { method: 'POST', key: '' }]);
  } finally { clear(); }
});

test('verified demo key handles all demo actions; live rejection disconnects it', async (context) => {
  clear();
  let live = false;
  const seen: string[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal((options.headers as Record<string, string>)['X-API-Key'], 'demo-key');
    if (url.endsWith('/security/identity')) return Response.json({ data: { role: 'demo_admin' } });
    seen.push(url);
    if (live) return Response.json({ detail: { code: 'DEMO_ADMIN_SIMULATION_ONLY',
      message: 'Use isolated simulation profile' } }, { status: 403 });
    return Response.json({ data: {} });
  });
  try {
    await api.verifyAndSaveRoleKey('demoAdmin', 'demo-key');
    assert.deepEqual(api.getConnectedRoles(), ['demoAdmin']);
    await api.proposeWithAgent('test');
    await api.createPolicy({ max_amount_wei: '1' });
    await api.decideApproval('test', 'APPROVE');
    await api.signProposal('test');
    assert.equal(seen.length, 4);
    live = true;
    await assert.rejects(() => api.signProposal('test'));
    assert.deepEqual(api.getConnectedRoles(), []);
    assert.equal(api.getRoleKey('demoAdmin'), '');
  } finally { clear(); }
});
