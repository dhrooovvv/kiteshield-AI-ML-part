import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

test('proposal cards emphasize their source and retain real transaction evidence without policy clutter', async () => {
  const server = await createServer({ configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null } });
  try {
    const { ProposalCard } = await server.ssrLoadModule('/src/components/ProposalCard.tsx');
    const hash = '0x' + 'a'.repeat(64);
    const base = { id: 'source-card', correlation_id: 'correlation', status: 'CONFIRMED',
      created_at: '2026-10-24T18:02:00Z', prompt: 'Original request is available in Details',
      recipient: '0x' + '11'.repeat(20), amount_eth: '0.000000000000000001', amount_wei: '1',
      chain_id: 11155111, policy_decision: { decision: 'ALLOW', reason_codes: ['ONE', 'TWO', 'THREE'] },
      transaction: { id: 'tx', tx_hash: hash, execution_mode: 'sepolia', execution_outcome: 'CONFIRMED' } };
    const render = (proposal: object) => renderToStaticMarkup(createElement(ProposalCard, {
      proposal, onUpdated() {}, onOpenAudit() {}, onOpenDetails() {}, executionMode: 'sepolia',
    }));
    for (const [provenance, title] of [
      ['invoice_intake', 'Invoice intake · verified vendor registry'],
      ['DETERMINISTIC_MANDATE', 'Treasury sweep · standing mandate'],
      ['AGENT_OR_STRUCTURED', 'Payment request'],
    ]) {
      const html = render({ ...base, provenance, mandate_version: 4 });
      assert.match(html, new RegExp(`<h3 class="proposal-card-source">${title}</h3>`));
      assert.doesNotMatch(html, /Policy decision|View reasons|proposal-card-prompt/);
      assert.match(html, /datetime="2026-10-24T18:02:00Z"/i);
      assert.match(html, /0\.000000000000000001/);
      assert.ok(html.includes(`https://sepolia.etherscan.io/tx/${hash}`));
      assert.match(html, /1 receipt, not finality/);
      assert.match(html, /Details|Audit trail/);
    }
    for (const transaction of [
      { ...base.transaction, execution_mode: 'simulated' },
      { ...base.transaction, tx_hash: '0x1234' },
      { ...base.transaction, execution_outcome: 'SIGNED' },
    ]) assert.doesNotMatch(render({ ...base, transaction }), /href=/);
    const pending = render({ ...base, status: 'ALLOWED', provenance: 'invoice_intake', transaction: null });
    assert.match(pending, /proposal-card-awaiting/);
    assert.match(pending, /Not submitted · no on-chain transaction/);
    assert.doesNotMatch(pending, /href=/);
    assert.ok(pending.indexOf('Sign &amp; broadcast') < pending.indexOf('<footer'));
    assert.match(render({ ...base, transaction: null }), /Transaction evidence unavailable/);
    const vaultHtml = render({...base, status: 'APPROVED', transaction: null, payment_backend: 'VAULT'});
    assert.match(vaultHtml, /Guarded vault|Autonomous tasks/);
    assert.doesNotMatch(vaultHtml, /Sign &amp; broadcast|Reconcile &amp; retry/);
  } finally { await server.close(); }
});

test('autonomous small payments omit manual signing, approved and over-cap keep it', async () => {
  const server = await createServer({
    configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  try {
    const { ProposalCard } = await server.ssrLoadModule('/src/components/ProposalCard.tsx');
    for (const [status, amount, automatic] of [
      ['ALLOWED', '20000000000000', true],
      ['APPROVED', '20000000000000', false],
      ['ALLOWED', '2000000000000000', false],
    ] as const) {
      const html = renderToStaticMarkup(createElement(ProposalCard, {
        proposal: { id: 'auto', status, created_at: '2026-10-18T00:00:00Z',
          prompt: 'Test', recipient: '0x' + '11'.repeat(20), amount_eth: '0.00002',
          amount_wei: amount, chain_id: 11155111, auto_execution_enabled: true,
          auto_execution_max_wei: '100000000000000' }, executionMode: 'sepolia',
        onUpdated: () => {}, onOpenAudit: () => {}, onOpenDetails: () => {},
      }));
      assert.match(html, /Auto-execution limit: 0.0001 ETH/);
      if (automatic) {
        assert.doesNotMatch(html, /Sign &amp; broadcast/);
        assert.match(html, /Recheck automatic execution/);
      } else assert.match(html, /Sign &amp; broadcast/);
    }
  } finally { await server.close(); }
});

test('live payment outcomes stay distinct and uncertain payments only retry the same execution', async () => {
  const server = await createServer({
    configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  try {
    const { ProposalCard } = await server.ssrLoadModule('/src/components/ProposalCard.tsx');
    for (const [outcome, status, message] of [
      ['UNCERTAIN', 'SIGNED', 'outcome uncertain'],
      ['SUBMITTED', 'SUBMITTED', 'submitted, awaiting receipt'],
      ['CONFIRMED', 'CONFIRMED', 'confirmed (1 receipt, not finality)'],
      ['REVERTED', 'TX_FAILED', 'reverted'],
    ]) {
      const html = renderToStaticMarkup(createElement(ProposalCard, {
        proposal: { id: 'p', created_at: '2026-10-17T00:00:00Z', status,
          prompt: 'Test payment', recipient: '0x' + '11'.repeat(20), amount_eth: '0.00001',
          chain_id: 11155111, transaction: { id: 't', tx_hash: '0x1234',
            execution_mode: 'sepolia', execution_outcome: outcome } },
        onUpdated: () => {}, onOpenAudit: () => {}, onOpenDetails: () => {},
      }));
      assert.ok(html.includes(message));
      if (outcome === 'UNCERTAIN') assert.match(html, /Reconcile &amp; retry same transaction/);
      else assert.doesNotMatch(html, /Reconcile &amp; retry same transaction/);
    }
  } finally {
    await server.close();
  }
});

// Exercise real components through Vite's existing TSX loader; no new test dependencies.
test('payment UI clearly labels simulation and never presents caller-entered approver identity', async () => {
  const server = await createServer({
    configFile: false, appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  try {
    const { Header } = await server.ssrLoadModule('/src/components/Header.tsx');
    const header = renderToStaticMarkup(createElement(Header, {
      health: { status: 'healthy', service: 'test', version: 'test', execution_mode: 'simulated' },
      title: 'Overview', onRefreshAll: () => {}, loading: false,
    }));
    assert.match(header, /Simulation · no on-chain broadcast/);
    const { ApprovalModal } = await server.ssrLoadModule('/src/components/ApprovalModal.tsx');
    const approval = renderToStaticMarkup(createElement(ApprovalModal, {
      approval: {
        id: 'approval', action_digest: 'digest', expires_at: '2030-01-01T00:00:00Z',
        proposal: { amount_eth: '0.03', amount_wei: '30000000000000000',
          recipient: '0x' + '11'.repeat(20), prompt: 'Test payment', chain_id: 11155111 },
      },
      onClose: () => {}, onDecided: () => {},
    }));
    assert.match(approval, /separate human-approver credential/);
    assert.doesNotMatch(approval, /value="user:|Approver Identity/);
    const { ProposalCard } = await server.ssrLoadModule('/src/components/ProposalCard.tsx');
    const card = renderToStaticMarkup(createElement(ProposalCard, {
      proposal: {
        id: 'proposal', created_at: '2026-10-17T00:00:00Z', status: 'SUBMITTED',
        prompt: 'Test payment', recipient: '0x' + '11'.repeat(20), amount_eth: '0.03',
        chain_id: 11155111, transaction: { tx_hash: '0x1234', execution_mode: 'simulated' },
      },
      onUpdated: () => {}, onOpenAudit: () => {}, onOpenDetails: () => {},
    }));
    assert.match(card, /Simulated · not broadcast/);
    assert.doesNotMatch(card, /etherscan.io|Sign &amp; broadcast/);
  } finally {
    await server.close();
  }
});

test('verified roles control the header and each restricted action independently', async (context) => {
  const server = await createServer({
    configFile: false, appType: 'custom', server: { middlewareMode: true, hmr: false, watch: null },
  });
  try {
    const { api: client } = await server.ssrLoadModule('/src/api/client.ts');
    // Render a selected client-store snapshot on the server; identity validation
    // itself still executes through the real API client below.
    context.mock.method(client, 'getServerConnectedRoles', () => client.getConnectedRoles());
    context.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
      const key = (options.headers as Record<string, string>)['X-API-Key'];
      return Response.json({ data: { role: key === 'human' ? 'human_approver'
        : key === 'admin' ? 'policy_administrator' : key === 'demo' ? 'demo_admin' : 'proposer' } });
    });
    const { Header } = await server.ssrLoadModule('/src/components/Header.tsx');
    const { PolicyCard } = await server.ssrLoadModule('/src/components/PolicyCard.tsx');
    const { ApprovalModal } = await server.ssrLoadModule('/src/components/ApprovalModal.tsx');
    const { ProposalCard } = await server.ssrLoadModule('/src/components/ProposalCard.tsx');
    const { AgentPromptBox } = await server.ssrLoadModule('/src/components/AgentPromptBox.tsx');
    const noop = () => {};
    const renderHeader = () => renderToStaticMarkup(createElement(Header, {
      title: 'Overview', health: { execution_mode: 'simulated' }, onRefreshAll: noop, loading: false,
    }));
    const renderPolicy = () => renderToStaticMarkup(createElement(PolicyCard, { policy: null, onPolicyUpdated: noop }));
    const renderApproval = () => renderToStaticMarkup(createElement(ApprovalModal, {
      approval: { id: 'a', action_digest: 'digest', expires_at: '2030-01-01T00:00:00Z',
        proposal: { amount_eth: '0.03', amount_wei: '30000000000000000', recipient: '0x' + '11'.repeat(20) } },
      onClose: noop, onDecided: noop,
    }));
    const renderPayment = () => renderToStaticMarkup(createElement(ProposalCard, {
      proposal: { id: 'p', status: 'ALLOWED', created_at: '2026-10-17T00:00:00Z',
        recipient: '0x' + '11'.repeat(20), amount_eth: '0.03', chain_id: 11155111, prompt: 'Test' },
      executionMode: 'simulated', onUpdated: noop, onOpenAudit: noop, onOpenDetails: noop,
    }));
    const buttonIsDisabled = (markup: string, text: string) => {
      const match = [...markup.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)]
        .find((item) => item[2].includes(text));
      assert.ok(match, 'Button exists: ' + text);
      return match[1].includes('disabled');
    };
    assert.match(renderHeader(), /Not authenticated/);
    assert.match(renderHeader(), /Switch role/);
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), true);
    assert.equal(buttonIsDisabled(renderApproval(), 'Approve Authorization'), true);
    assert.equal(buttonIsDisabled(renderApproval(), 'Reject Proposal'), true);
    assert.equal(buttonIsDisabled(renderPayment(), 'Sign &amp; simulate'), true);
    const agent = renderToStaticMarkup(createElement(AgentPromptBox, { onProposalCreated: noop }));
    assert.equal(buttonIsDisabled(agent, 'Allowed Transfer'), true);
    await client.verifyAndSaveRoleKey('proposer', 'proposal');
    assert.equal(buttonIsDisabled(renderPayment(), 'Sign &amp; simulate'), false);
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), true);
    assert.equal(buttonIsDisabled(renderApproval(), 'Approve Authorization'), true);
    await client.verifyAndSaveRoleKey('approver', 'human');
    assert.equal(buttonIsDisabled(renderApproval(), 'Approve Authorization'), false);
    assert.equal(buttonIsDisabled(renderApproval(), 'Reject Proposal'), false);
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), true);
    await client.verifyAndSaveRoleKey('policyAdmin', 'admin');
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), false);
    const header = renderHeader();
    assert.match(header, /Connected roles/);
    assert.match(header, /Proposer · Human approver · Policy administrator/);
    assert.match(header, /Simulation · no on-chain broadcast/);
    client.setRoleKey('policyAdmin', '');
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), true);
    assert.equal(buttonIsDisabled(renderPayment(), 'Sign &amp; simulate'), false);
    client.setApiKey('');
    client.setRoleKey('approver', '');
    client.setRoleKey('policyAdmin', '');
    await client.verifyAndSaveRoleKey('demoAdmin', 'demo');
    assert.match(renderHeader(), /Demo administrator \(simulation only\)/);
    assert.equal(buttonIsDisabled(renderPolicy(), 'Create Initial Policy'), false);
    assert.equal(buttonIsDisabled(renderApproval(), 'Approve Authorization'), false);
    assert.equal(buttonIsDisabled(renderPayment(), 'Sign &amp; simulate'), false);
    client.setRoleKey('demoAdmin', '');
    assert.equal(buttonIsDisabled(renderPayment(), 'Sign &amp; simulate'), true);
  } finally { await server.close(); }
});
