import assert from 'node:assert/strict';
import test from 'node:test';
import { refreshPaymentReceipts } from '../src/paymentReceipts.ts';
import type { Proposal, Transaction } from '../src/types/index.ts';

const proposal = (mode = 'sepolia') => ({
  id: 'p', status: 'SUBMITTED', transaction: { id: 't', status: 'SUBMITTED', execution_mode: mode },
} as Proposal);

test('dashboard receipt refresh updates confirmed and reverted payments without submitting', async () => {
  for (const [status, expected] of [['CONFIRMED', 'CONFIRMED'], ['FAILED', 'TX_FAILED']]) {
    let calls = 0;
    const result = await refreshPaymentReceipts([proposal()], async (id) => {
      assert.equal(id, 't'); calls++;
      return { id, status, execution_mode: 'sepolia' } as Transaction;
    });
    assert.equal(calls, 1);
    assert.equal(result.proposals[0].status, expected);
    assert.equal(result.failed, false);
  }
});

test('simulation is never queried as on-chain evidence; RPC failures retain uncertain state', async () => {
  const simulated = await refreshPaymentReceipts([proposal('simulated')], async () => {
    throw new Error('must not query simulation');
  });
  assert.equal(simulated.failed, false);
  const live = proposal();
  live.transaction!.status = 'SIGNED';
  live.transaction!.execution_outcome = 'UNCERTAIN';
  const result = await refreshPaymentReceipts([live], async () => { throw new Error('offline'); });
  assert.equal(result.failed, true);
  assert.equal(result.proposals[0].transaction!.execution_outcome, 'UNCERTAIN');
});
