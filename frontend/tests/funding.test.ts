import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { fundingExplorer, fundingMessage } from '../src/funding.ts';
import type { FundingRequest } from '../src/funding.ts';
const request: FundingRequest = { id: 'request', address: '0x' + '11'.repeat(20), mode: 'sepolia',
  state: 'SUBMITTED', reason: null, chain_id: 11155111, tx_hash: '0x' + 'ab'.repeat(32),
  amount_wei: null, block_number: null, created_at: '2026-10-25T00:00:00Z', explorer_url: 'https://evil.example' };
test('only real Sepolia hashes produce fixed explorer links', () => {
  assert.equal(fundingExplorer(request), `https://sepolia.etherscan.io/tx/${request.tx_hash}`);
  for (const patch of [{ mode: 'simulated' }, { state: 'SIMULATED' }, { chain_id: 1 },
    { tx_hash: null }, { tx_hash: 'bad' }, { state: 'UNCERTAIN' }]) {
    assert.equal(fundingExplorer({ ...request, ...patch } as FundingRequest), null);
  }
});
test('pending and simulated requests never claim successful funding', () => {
  assert.match(fundingMessage(request), /waiting for a receipt/);
  assert.match(fundingMessage({ ...request, state: 'SIMULATED' }), /no test ETH received/);
  assert.match(fundingMessage({ ...request, state: 'UNCERTAIN' }), /do not request again/);
});
test('funding evidence renders exact wei and safe transaction links', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { FundingEvidence } = await server.ssrLoadModule('/src/components/FundingDialog.tsx');
    const render = (data: FundingRequest) => renderToStaticMarkup(createElement(FundingEvidence, { request: data }));
    const html = render({ ...request, state: 'CONFIRMED', amount_wei: '1' });
    assert.match(html, /0\.000000000000000001 ETH received/);
    assert.match(html, /Wallet funded/);
    assert.doesNotMatch(html, /evil\.example/);
    assert.doesNotMatch(render({ ...request, mode: 'simulated', state: 'SIMULATED' }), /href=|Wallet funded/);
  } finally { await server.close(); }
});
