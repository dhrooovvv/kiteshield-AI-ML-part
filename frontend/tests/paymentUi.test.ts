import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

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
