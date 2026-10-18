import assert from 'node:assert/strict';
import test from 'node:test';
import { api, KiteShieldAPIError } from '../src/api/client.ts';

for (const code of ['PROMPT_INJECTION_DETECTED', 'PROMPT_SCREENING_REVIEW_REQUIRED']) {
  test(`${code} notifies refresh immediately and remains a rejected proposal`, async (context) => {
    let refreshes = 0;
    const unsubscribe = api.subscribeScreeningEvents(() => { refreshes++; });
    context.mock.method(globalThis, 'fetch', async () => Response.json({
      error: { code, message: 'Synthetic screening rejection' },
    }, { status: code === 'PROMPT_INJECTION_DETECTED' ? 422 : 409 }));
    try {
      await assert.rejects(() => api.proposeWithAgent('isolated test'),
        (error: unknown) => error instanceof KiteShieldAPIError && error.code === code);
      assert.equal(refreshes, 1);
      unsubscribe();
      await assert.rejects(() => api.proposeWithAgent('isolated test'));
      assert.equal(refreshes, 1);
    } finally { unsubscribe(); }
  });
}

test('blocked aggregate is fetched from the backend and is not limited to displayed proposals', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url: string) => {
    assert.equal(url, '/api/v1/audit/screening-counts');
    return Response.json({ data: { blocked_count: 78, screening_block_count: 70, policy_block_count: 8 } });
  });
  assert.equal((await api.getScreeningCounts()).blocked_count, 78);
});

test('each review refresh fetches fresh authenticated backend data', async (context) => {
  let requests = 0;
  const fakeFetch = context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.match(url, /\/audit\/prompt-reviews/);
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal);
    assert.equal((options.headers as Record<string, string>)['X-API-Key'], 'synthetic-test-key');
    requests++;
    return Response.json({ data: [{ id: 'review-' + requests }] });
  });
  api.setApiKey('synthetic-test-key');
  try {
    assert.equal((await api.listPromptScreeningReviews())[0].id, 'review-1');
    assert.equal((await api.listPromptScreeningReviews())[0].id, 'review-2');
    assert.equal(fakeFetch.mock.callCount(), 2);
  } finally { api.setApiKey(''); }
});

test('refresh failures remain errors rather than becoming an empty review queue', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ error: { code: 'UNAUTHORIZED', message: 'Invalid API key' } }, { status: 401 }));
  await assert.rejects(() => api.listPromptScreeningReviews(), (error: unknown) => error instanceof KiteShieldAPIError && error.status === 401);
});

test('transaction approval decisions use the existing approval endpoint', async (context) => {
  const decisions: string[] = [];
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/approvals/approval-test/decide');
    assert.equal(options.method, 'POST');
    const body = JSON.parse(options.body as string);
    decisions.push(body.decision);
    return Response.json({ data: { id: 'approval-test', status: body.decision } });
  });
  await api.decideApproval('approval-test', 'APPROVE');
  await api.decideApproval('approval-test', 'REJECT');
  assert.deepEqual(decisions, ['APPROVE', 'REJECT']);
});

test('credential verification is read-only and uses the candidate before saving', async (context) => {
  api.setApiKey('previous-proposer');
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/security/identity');
    assert.equal(options.method, 'GET');
    assert.equal((options.headers as Record<string, string>)['X-API-Key'], 'candidate-proposer');
    assert.equal(api.getApiKey(), 'previous-proposer');
    return Response.json({ data: { role: 'proposer' } });
  });
  try {
    await api.verifyAndSaveRoleKey('proposer', '  candidate-proposer  ');
    assert.equal(api.getApiKey(), 'candidate-proposer');
  } finally { api.setApiKey(''); }
});

test('rejected credentials do not replace a working saved credential', async (context) => {
  api.setApiKey('previous-proposer');
  context.mock.method(globalThis, 'fetch', async () => Response.json({
    detail: { code: 'INVALID_API_KEY', message: 'Invalid API key' },
  }, { status: 401 }));
  try {
    await assert.rejects(() => api.verifyAndSaveRoleKey('proposer', 'invalid-candidate'),
      (error: unknown) => error instanceof KiteShieldAPIError && error.status === 401);
    assert.equal(api.getApiKey(), 'previous-proposer');
  } finally { api.setApiKey(''); }
});

test('blank and unexpected authentication responses never save a key', async (context) => {
  api.setRoleKey('approver', 'previous-approver');
  const fetch = context.mock.method(globalThis, 'fetch', async () => Response.json({ data: 'unexpected' }));
  try {
    await assert.rejects(() => api.verifyAndSaveRoleKey('approver', ' '));
    assert.equal(fetch.mock.callCount(), 0);
    await assert.rejects(() => api.verifyAndSaveRoleKey('approver', 'candidate-approver'));
    assert.equal(api.getRoleKey('approver'), 'previous-approver');
    assert.equal(api.getApiKey(), '');
  } finally { api.setRoleKey('approver', ''); }
});
