import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { safeAssistantExplorer, assistantExamples } from '../src/assistant.ts';
test('assistant examples include useful questions beyond funding', () => {
  assert.ok(assistantExamples.some(value => /last month/.test(value)));
  assert.ok(assistantExamples.some(value => /biggest/.test(value)));
});
test('assistant links are restricted to actual Sepolia transaction hashes', () => {
  const real = 'https://sepolia.etherscan.io/tx/0x' + 'ab'.repeat(32);
  assert.equal(safeAssistantExplorer(real), real);
  for (const url of [null, 'javascript:alert(1)', 'https://evil.example',
    'https://etherscan.io/tx/0x' + 'ab'.repeat(32), real + '?redirect=evil', 'simulated']) {
    assert.equal(safeAssistantExplorer(url), null);
  }
});
test('assistant renders grounded amounts, unavailable balances and safe history', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { AssistantResult } = await server.ssrLoadModule('/src/components/AssistantDialog.tsx');
    const render = (answer: object) => renderToStaticMarkup(createElement(AssistantResult, { answer }));
    const unavailable = render({ kind: 'balance', title: 'Balances',
      data: { status: 'unavailable', message: 'RPC failed', holdings: [] } });
    assert.match(unavailable, /RPC failed/);
    assert.doesNotMatch(unavailable, /0 ETH|Funded/);
    const html = render({ kind: 'payments', title: 'Recorded spending', data: {
      total_eth: '0.000000000000000109', period: 'Last month (UTC)', count: 2,
      basis: 'Recorded payments; excludes gas.', payments: [{ proposal_id: 'p',
        amount_eth: '0.0000000000000001', recipient: '<script>attack</script>',
        recorded_at: '2026-10-01T00:00:00Z', status: 'CONFIRMED', explorer_url: 'https://evil.example' }],
    } });
    assert.match(html, /0\.000000000000000109/);
    assert.match(html, /excludes gas/);
    assert.doesNotMatch(html, /href="https:\/\/evil|<script>/);
  } finally { await server.close(); }
});
