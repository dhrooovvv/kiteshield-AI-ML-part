import test from 'node:test';
import assert from 'node:assert/strict';
import { api } from '../src/api/client.ts';
import { autonomyAvailable, autonomyRequest, goalSubmission, autonomyStepState, transactionLinks } from '../src/autonomy.ts';

test('autonomy stays hidden when backend is absent, disabled or reports an unsupported mode', async () => {
  const original = globalThis.fetch;
  try {
    for (const body of [{enabled: false, mode: 'SIMULATED'}, {enabled: true, mode: 'sepolia'}]) {
      globalThis.fetch = async () => new Response(JSON.stringify(body));
      assert.equal(await autonomyAvailable(), false);
    }
    globalThis.fetch = async () => new Response('missing', {status: 404});
    assert.equal(await autonomyAvailable(), false);
  } finally { globalThis.fetch = original; }
});

test('explicit Sepolia adapter is available and only validated chain hashes produce explorer links', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({enabled: true, mode: 'SEPOLIA'}));
    assert.equal(await autonomyAvailable(), true);
    const hash = '0x' + 'a'.repeat(64);
    const task = {id: 'task', amount: 1, state: 'COMPLETED', reason: null, payment_cap: 1, funding_cap: 1, events: [],
      steps: [
        {position: 0, tool: 'fund', state: 'COMPLETED', result: JSON.stringify({mode: 'SIMULATED', tx_hash: hash})},
        {position: 1, tool: 'payment', state: 'COMPLETED', result: JSON.stringify({mode: 'SEPOLIA', tx_hash: hash, explorer_url: 'javascript:evil'})},
        {position: 2, tool: 'receipt', state: 'COMPLETED', result: JSON.stringify({mode: 'SEPOLIA', tx_hash: hash})},
      ]};
    assert.deepEqual(transactionLinks(task), [{hash, url: `https://sepolia.etherscan.io/tx/${hash}`}]);
  } finally { globalThis.fetch = original; }
});

test('agent role cannot supply an administrator action credential', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  try {
    globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({data: {role: 'proposer'}}), {headers: {'content-type': 'application/json'}}); };
    await api.verifyAndSaveRoleKey('proposer', 'fixture-agent-key-only');
    const before = calls;
    await assert.rejects(autonomyRequest('/quarantine/resume', 'policyAdmin', {}), /Connect/);
    await assert.rejects(autonomyRequest('/approvals/task/decision', 'approver', {decision: 'APPROVE'}), /Connect/);
    assert.equal(calls, before);
  } finally { globalThis.fetch = original; api.setApiKey(''); }
});

test('retry after a lost task response reuses the request key until acknowledged', () => {
  let generated = 0;
  const makeKey = () => String(++generated);
  const first = goalSubmission(null, 'pay supplier', makeKey);
  assert.equal(goalSubmission(first, 'pay supplier', makeKey).key, first.key);
  assert.notEqual(goalSubmission(null, 'pay supplier', makeKey).key, first.key);
  assert.notEqual(goalSubmission(first, 'pay another supplier', makeKey).key, first.key);
});

test('terminal rejected tasks never advertise a pending payment or ready verification', () => {
  assert.equal(autonomyStepState('REJECTED', 'WAITING'), 'NOT_EXECUTED');
  assert.equal(autonomyStepState('REJECTED', 'READY'), 'NOT_EXECUTED');
  assert.equal(autonomyStepState('REJECTED', 'COMPLETED'), 'COMPLETED');
  assert.equal(autonomyStepState('WAITING_APPROVAL', 'WAITING'), 'WAITING');
  assert.equal(autonomyStepState('HUMAN_REQUIRED', 'RUNNING'), 'ON_HOLD');
});

test('unreadable proxy response gives a recovery instruction, not raw JSON errors', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({data: {role: 'proposer'}}), {headers: {'content-type': 'application/json'}});
    await api.verifyAndSaveRoleKey('proposer', 'fixture-agent-key-only');
    globalThis.fetch = async () => new Response('', {status: 503});
    await assert.rejects(autonomyRequest('/snapshot'), /Check task history/);
  } finally { globalThis.fetch = original; api.setApiKey(''); }
});
