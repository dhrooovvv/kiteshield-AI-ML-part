import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

test('live header requires verified Sepolia chain and block; simulation remains explicit', async () => {
  const server = await createServer({
    configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  try {
    const { Header } = await server.ssrLoadModule('/src/components/Header.tsx');
    const render = (health: object | null) => renderToStaticMarkup(createElement(Header, {
      health, title: 'Overview', onRefreshAll: () => {}, loading: false,
    }));
    const base = { status: 'healthy', service: 'test', version: 'test', execution_mode: 'sepolia' };
    const live = render({ ...base, verified_chain_id: 11155111,
      verified_block_number: 12345678, rpc_verified_at: '2026-10-18T00:00:00Z' });
    assert.match(live, /Sepolia · chain 11155111 · block 12345678/);
    assert.match(live, /execution-mode-live/);
    assert.match(live, /latest observed at startup/);
    for (const health of [base, { ...base, verified_chain_id: 1, verified_block_number: 10 },
      { ...base, verified_chain_id: 11155111, verified_block_number: null },
      { ...base, verified_chain_id: 11155111, verified_block_number: -1 }]) {
      const html = render(health);
      assert.match(html, /Execution mode unverified/);
      assert.doesNotMatch(html, /execution-mode-live|Sepolia · chain/);
    }
    assert.match(render({ ...base, execution_mode: 'simulated' }), /Simulation · no on-chain broadcast/);
    assert.match(render(null), /Execution mode unavailable/);
  } finally {
    await server.close();
  }
});
