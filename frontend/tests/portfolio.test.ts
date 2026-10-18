import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { api } from '../src/api/client.ts';
import { initialPortfolioRead, portfolioReadReducer } from '../src/portfolio.ts';
import type { PortfolioSnapshot } from '../src/portfolio.ts';

test('refresh preserves the rendered snapshot and its age until an atomic replacement', () => {
  const first = { mode: 'sepolia' } as PortfolioSnapshot;
  const second = { mode: 'simulated' } as PortfolioSnapshot;
  const loaded = portfolioReadReducer(initialPortfolioRead,
    { type: 'success', data: first, at: 1000 });
  const refreshing = portfolioReadReducer(loaded, { type: 'start' });
  assert.equal(refreshing.data, first);
  assert.equal(refreshing.loadedAt, 1000);
  assert.equal(refreshing.refreshing, true);
  const complete = portfolioReadReducer(refreshing,
    { type: 'success', data: second, at: 5000 });
  assert.equal(complete.data, second);
  assert.equal(complete.loadedAt, 5000);
  assert.equal(complete.refreshing, false);
});

test('failed read clears old balances instead of presenting them as current', () => {
  const loaded = portfolioReadReducer(initialPortfolioRead, {
    type: 'success', data: { mode: 'sepolia' } as PortfolioSnapshot, at: 1000,
  });
  const failed = portfolioReadReducer(portfolioReadReducer(loaded, { type: 'start' }),
    { type: 'failure', message: 'Portfolio unavailable' });
  assert.equal(failed.data, null);
  assert.equal(failed.loadedAt, null);
  assert.equal(failed.refreshing, false);
  assert.equal(failed.error, 'Portfolio unavailable');
});

test('portfolio API is GET only and re-fetches rather than inventing cached data', async context => {
  const calls = context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/portfolio');
    assert.equal(options.method ?? 'GET', 'GET');
    assert.equal(options.cache, 'no-store');
    return Response.json({ data: { mode: 'simulated', network: { status: 'unavailable' } } });
  });
  await api.getPortfolio(); await api.getPortfolio();
  assert.equal(calls.mock.callCount(), 2);
});

test('portfolio labels simulation, unavailable balances and never links simulated hashes', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { PortfolioContent } = await server.ssrLoadModule('/src/views/PortfolioView.tsx');
    const data = {
      mode: 'simulated', network: { status: 'unavailable', message: 'Wrong chain.', holdings: [] },
      budget: { status: 'available', period: 'UTC calendar day', date: '2026-10-18',
        policy_version: 6, daily_limit_eth: '1', spent_today_eth: '0.1', pending_eth: '0.2',
        remaining_eth: '0.7', spent_percent: '10', pending_percent: '20',
        auto_execute_enabled: false, autonomous_cap_eth: '0.0001',
        escalation_threshold_eth: '0.5', absolute_max_eth: '1' },
      recent_payments: [{ proposal_id: 'p', status: 'SIMULATED', amount_eth: '0.00001',
        recipient: '0x' + '11'.repeat(20), tx_hash: '0x' + 'ab'.repeat(32),
        explorer_url: 'https://sepolia.etherscan.io/tx/should-never-appear' }],
    };
    let html = renderToStaticMarkup(createElement(PortfolioContent, { data }));
    assert.match(html, /testnet, no market value/);
    assert.match(html, /Holdings unavailable/);
    assert.match(html, /Simulated · not broadcast/);
    assert.doesNotMatch(html, /etherscan|Sign &amp; broadcast|Propose|Approve/);
    assert.match(html, /Budget: spent 0.1 ETH, pending 0.2 ETH, remaining 0.7 ETH/);
    data.recent_payments[0].status = 'CONFIRMED';
    data.recent_payments[0].explorer_url = 'https://sepolia.etherscan.io/tx/' + '0x' + 'ab'.repeat(32);
    html = renderToStaticMarkup(createElement(PortfolioContent, { data }));
    assert.match(html, /href="https:\/\/sepolia.etherscan.io\/tx\/0xabab/);
  } finally { await server.close(); }
});

test('portfolio ledger puts holdings and recent payments before the budget rail without losing exact values', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { PortfolioContent } = await server.ssrLoadModule('/src/views/PortfolioView.tsx');
    const address = '0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7';
    const html = renderToStaticMarkup(createElement(PortfolioContent, { data: {
      mode: 'sepolia', network: { status: 'available', chain_id: 11155111,
        block_number: 11940128, block_timestamp: '2026-10-18T09:28:48Z', pending_nonce: 5,
        holdings: [{ asset: 'ETH', token_address: null, address, role: 'Signer wallet (hot)',
          address_url: `https://sepolia.etherscan.io/address/${address}`,
          balance: '0.0499099999951358', share_percent: '100.000000' }] },
      budget: { status: 'available', period: 'UTC calendar day', date: '2026-10-18',
        policy_version: 6, daily_limit_eth: '5', spent_today_eth: '0.00009', pending_eth: '0',
        remaining_eth: '4.99991', spent_percent: '0.0018', pending_percent: '0',
        auto_execute_enabled: true, autonomous_cap_eth: '0.0001',
        escalation_threshold_eth: '0.5', absolute_max_eth: '1' }, recent_payments: [],
    } }));
    assert.match(html, /portfolio-dashboard-grid/);
    assert.ok(html.indexOf('portfolio-holdings') < html.indexOf('portfolio-payments'));
    assert.ok(html.indexOf('portfolio-payments') < html.indexOf('portfolio-budget'));
    assert.match(html, /<aside class="portfolio-section portfolio-budget"/);
    assert.doesNotMatch(html, /glass-panel/);
    assert.match(html, /title="0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7"/);
    assert.match(html, /0.0499099999951358/);
    assert.match(html, /100.000000%/);
    assert.match(html, /<details class="portfolio-explainer"><summary>Details/);
    assert.doesNotMatch(html, /portfolio-context|Live RPC balances|Read-only snapshot/);
    assert.match(html, /UTC calendar day/);
    assert.doesNotMatch(html, /Sign &amp; broadcast|Create proposal/);
  } finally { await server.close(); }
});
