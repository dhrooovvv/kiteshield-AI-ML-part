import assert from 'node:assert/strict';
import test from 'node:test';
import { api } from '../src/api/client.ts';
import { previewTreasury, saveAndPreviewTreasury } from '../src/treasuryWorkflow.ts';
import type { TreasuryConfig, TreasuryStatus } from '../src/treasury.ts';

const saved = { mode: 'off', mandate: { version: 12 } } as TreasuryStatus;
const config = { chain_id: 11155111 } as TreasuryConfig;

test('Save & preview uses returned version, enables only planning, then observes', async context => {
  const calls: string[] = [];
  context.mock.method(api, 'saveTreasury', async (_config: TreasuryConfig, version: number) => {
    assert.equal(version, 11); calls.push('save'); return saved;
  });
  context.mock.method(api, 'setTreasuryMode', async (mode: string, version: number) => {
    assert.equal(mode, 'plan_only'); assert.equal(version, 12); calls.push('plan'); return saved;
  });
  context.mock.method(api, 'observeTreasury', async () => { calls.push('observe'); return saved; });
  await saveAndPreviewTreasury(config, 11, () => { calls.push('saved'); });
  assert.deepEqual(calls, ['save', 'saved', 'plan', 'observe']);
});

test('save failure never enables planning or observes', async context => {
  context.mock.method(api, 'saveTreasury', async () => { throw new Error('version conflict'); });
  const mode = context.mock.method(api, 'setTreasuryMode');
  const observe = context.mock.method(api, 'observeTreasury');
  await assert.rejects(saveAndPreviewTreasury(config, 11, () => assert.fail()), /version conflict/);
  assert.equal(mode.mock.callCount(), 0); assert.equal(observe.mock.callCount(), 0);
});

test('partial failure is explicit; retry previews without another save', async context => {
  const save = context.mock.method(api, 'saveTreasury', async () => saved);
  let modeCalls = 0;
  context.mock.method(api, 'setTreasuryMode', async () => {
    if (++modeCalls === 1) throw new Error('version conflict');
    return saved;
  });
  const observe = context.mock.method(api, 'observeTreasury', async () => saved);
  await assert.rejects(saveAndPreviewTreasury(config, 11, () => {}), /Mandate saved.*Execution was not enabled/);
  assert.equal(observe.mock.callCount(), 0);
  await previewTreasury(saved);
  assert.equal(save.mock.callCount(), 1);
  assert.equal(observe.mock.callCount(), 1);
});

test('preview in plan or execute mode observes only, preserving existing mode', async context => {
  const mode = context.mock.method(api, 'setTreasuryMode');
  const observe = context.mock.method(api, 'observeTreasury', async () => saved);
  for (const activeMode of ['plan_only', 'execute'] as const) await previewTreasury({ ...saved, mode: activeMode });
  assert.equal(mode.mock.callCount(), 0); assert.equal(observe.mock.callCount(), 2);
});

test('observation failure never proceeds to execution', async context => {
  context.mock.method(api, 'saveTreasury', async () => saved);
  const mode = context.mock.method(api, 'setTreasuryMode', async () => saved);
  context.mock.method(api, 'observeTreasury', async () => { throw new Error('RPC unavailable'); });
  await assert.rejects(saveAndPreviewTreasury(config, 11, () => {}), /Mandate saved.*RPC unavailable/);
  assert.equal(mode.mock.callCount(), 1);
  assert.equal(mode.mock.calls[0].arguments[0], 'plan_only');
});
