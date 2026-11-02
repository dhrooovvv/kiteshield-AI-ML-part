import test from 'node:test';
import assert from 'node:assert/strict';
import { vaultReady, type VaultStatus } from '../src/vault.ts';

const ready: VaultStatus = {enabled: true, payments_enabled: true, configured: true, epoch: 1,
  chain: {remaining: '40000000000000', perPayment: '40000000000000', balance: '40000000000000',
    agent_balance: '1000000000', expires: 2000, paused: false, epoch: 1}};
test('requires a current funded administrator grant', () => {
    assert.equal(vaultReady(ready, 1000000), true);
    assert.equal(vaultReady(undefined, 1000000), false);
    assert.equal(vaultReady({...ready, configured: false}, 1000000), false);
    assert.equal(vaultReady({...ready, payments_enabled: false}, 1000000), false);
    assert.equal(vaultReady({...ready, epoch: 2}, 1000000), false);
  });
test('blocks paused, expired, empty or unfunded sessions', () => {
    for (const patch of [{paused: true}, {expires: 999}, {remaining: '0'}, {balance: '0'}, {agent_balance: '0'}]) {
      assert.equal(vaultReady({...ready, chain: {...ready.chain!, ...patch}}, 1000000), false);
    }
    assert.equal(vaultReady(ready, 2000000), false);
  });
