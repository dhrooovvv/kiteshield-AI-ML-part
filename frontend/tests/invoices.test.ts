import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { api } from '../src/api/client.ts';
import { counterfactualLabel, invoiceEventLabel, invoiceExplorer, redTeamCounts, invoiceFileError } from '../src/invoices.ts';
import type { Invoice, InvoiceRedTeam, InvoiceSnapshot } from '../src/invoices.ts';

test('new vendor fields and submit remain visible for an invalid ID; registered IDs are listed', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
  try {
    const { VendorForm, VendorRegistry } = await server.ssrLoadModule('/src/views/InvoicesView.tsx');
    const vendor = { id: 'Northstar Services', name: '', payout_address: '', maximum_wei: '0', version: 0, active: true };
    const html = renderToStaticMarkup(createElement(VendorForm, { vendor, create: true, allowed: true, onSaved() {} }));
    assert.match(html, /Vendor ID/);
    assert.match(html, /Vendor name/);
    assert.match(html, /Payout address/);
    assert.match(html, /Maximum per invoice/);
    assert.match(html, /aria-invalid="true"/);
    assert.match(html, /type="submit" disabled="">Add vendor/);
    assert.match(html, /northstar-demo/);
    const registered = { ...vendor, id: 'northstar-demo', name: 'Northstar Services', maximum_wei: '50000000000000', version: 1 };
    const registry = renderToStaticMarkup(createElement(VendorRegistry, { vendors: [registered], allowed: false, onSaved() {} }));
    assert.match(registry, /Vendor ID: <code>northstar-demo<\/code>/);
    assert.match(registry, /Policy administrator/);
    assert.match(registry, /disabled=""[^>]*>Add vendor/);
    assert.doesNotMatch(registry, /<form|<details/);
    const lockedForm = renderToStaticMarkup(createElement(VendorForm, { vendor: registered, allowed: false, onSaved() {} }));
    assert.match(lockedForm, /fieldset disabled/);
  } finally { await server.close(); }
});

const invoice: Invoice = { id: 'invoice-1', document_hash: 'hash', state: 'SIMULATED', reason: null,
  vendor_id: null, proposal_id: null, extraction: null, checks: null, latency_ms: null,
  created_at: '2026-10-24T10:00:00Z', provenance: 'invoice_intake', proposal_status: 'SIMULATED',
  execution_mode: 'sepolia', transaction_hash: '0x123', explorer_url: 'https://sepolia.etherscan.io/tx/0x123',
  events: [{ stage: 'observed', reason: null, at: '2026-10-24T10:00:00Z' }] };
const report: InvoiceRedTeam = { available: true, simulation_only: true, attempts: [{ id: 'synthetic-1',
  category: 'Injection', first_stop: 'screening', reasons: [{ layer: 'screening', code: 'INJECTION' }],
  without_layer: { screening: { would_pass_checks: null, remaining_reasons: [] },
    policy: { would_pass_checks: false, remaining_reasons: ['INJECTION'] },
    vendor: { would_pass_checks: true, remaining_reasons: [] } } }] };

test('simulation never links to an explorer, even with inconsistent execution metadata', () => {
  assert.equal(invoiceExplorer(invoice), null);
  assert.equal(invoiceExplorer({ ...invoice, state: 'SUBMITTED', proposal_status: 'SUBMITTED', execution_mode: 'simulated' }), null);
  assert.equal(invoiceExplorer({ ...invoice, state: 'SUBMITTED', proposal_status: null, explorer_url: 'javascript:alert(1)' }), null);
  assert.match(invoiceEventLabel('paid'), /submitted, not confirmed/);
  assert.match(invoiceEventLabel('verified'), /matching receipt/);
  const hash = '0x' + 'a'.repeat(64);
  const real = { ...invoice, state: 'VERIFIED', proposal_status: 'CONFIRMED',
    transaction_hash: hash, explorer_url: `https://sepolia.etherscan.io/tx/${hash}` };
  assert.equal(invoiceExplorer(real), real.explorer_url);
  assert.equal(invoiceExplorer({ ...real, explorer_url: `https://example.com/tx/${hash}` }), null);
});

test('missing-vendor rechecks need proposer permission and never fabricate transaction links', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
  try {
    const { InvoiceActivity } = await server.ssrLoadModule('/src/views/InvoicesView.tsx');
    const blocked = { ...invoice, state: 'BLOCKED', reason: 'EXACT_VENDOR_REQUIRED', can_recheck: true,
      proposal_status: null, transaction_hash: null, explorer_url: null };
    const data: InvoiceSnapshot = { items: [blocked], intake_enabled: true, automatic_execution_enabled: false,
      live_execution_enabled: false, execution_mode: 'sepolia', no_action: null };
    const locked = renderToStaticMarkup(createElement(InvoiceActivity, { data, onRecheck() {} }));
    assert.match(locked, /disabled=""[^>]*>Recheck eligibility/);
    assert.match(locked, /Not submitted · no transaction link/);
    assert.doesNotMatch(locked, /href=/);
    const allowed = renderToStaticMarkup(createElement(InvoiceActivity, { data, canRecheck: true, onRecheck() {} }));
    assert.match(allowed, /Recheck eligibility/);
    assert.doesNotMatch(allowed, /disabled=/);
    const checked = renderToStaticMarkup(createElement(InvoiceActivity, { data: { ...data,
      items: [{ ...blocked, state: 'CHECKED', can_recheck: false }] }, canRecheck: true, onRecheck() {} }));
    assert.doesNotMatch(checked, /Recheck eligibility|href=/);
  } finally { await server.close(); }
});

test('unknown counterfactuals are never counted as passing', () => {
  assert.deepEqual(redTeamCounts(report), { attempts: 1, stopped: 1, wouldPass: 1, unknown: 1 });
  assert.equal(counterfactualLabel({ would_pass_checks: null, remaining_reasons: [] }), 'Unknown');
});

test('invoice reads and role-specific writes preserve paths, version and decimal strings', async context => {
  const calls: { url: string; options: RequestInit }[] = [];
  api.setApiKey('mock-proposer'); api.setRoleKey('policyAdmin', 'mock-admin');
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, options }); return Response.json({ data: {} });
  });
  try {
    await api.getInvoices(); await api.getInvoiceVendors(); await api.getInvoiceRedTeam();
    assert.ok(calls.every(call => (call.options.method ?? 'GET') === 'GET'));
    const update = { name: 'Vendor', payout_address: '0x' + '1'.repeat(40), maximum_eth: '0.000000000000000001', expected_version: 7, active: false };
    await api.updateInvoiceVendor('a/b', update); await api.submitInvoice('Invoice text'); await api.observeInvoices();
    assert.match(calls[3].url, /invoices\/vendors\/a%2Fb$/);
    assert.deepEqual(JSON.parse(calls[3].options.body as string), update);
    assert.equal((calls[3].options.headers as Record<string, string>)['X-API-Key'], 'mock-admin');
    assert.equal((calls[4].options.headers as Record<string, string>)['X-API-Key'], 'mock-proposer');
    assert.deepEqual(JSON.parse(calls[4].options.body as string), { text: 'Invoice text' });
    assert.equal(calls[5].options.body, undefined);
    assert.equal((calls[5].options.headers as Record<string, string>)['X-API-Key'], 'mock-admin');
    const file = new File(['invoice bytes'], 'invoice 01.pdf');
    await api.uploadInvoice(file);
    assert.match(calls[6].url, /invoices\/upload\?filename=invoice%2001.pdf$/);
    assert.equal(calls[6].options.body, file);
    assert.equal((calls[6].options.headers as Record<string, string>)['Content-Type'], 'application/octet-stream');
    assert.equal((calls[6].options.headers as Record<string, string>)['X-API-Key'], 'mock-proposer');
    await api.recheckInvoice('invoice/id');
    assert.match(calls[7].url, /invoices\/invoice%2Fid\/recheck$/);
    assert.equal(calls[7].options.method, 'POST');
    assert.equal((calls[7].options.headers as Record<string, string>)['X-API-Key'], 'mock-proposer');
  } finally { api.setApiKey(''); api.setRoleKey('policyAdmin', ''); }
});

test('rendered activity contains only actual events and simulation has no explorer link', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
  try {
    const { InvoiceActivity, InvoiceScoreboard, InvoicesView } = await server.ssrLoadModule('/src/views/InvoicesView.tsx');
    const data: InvoiceSnapshot = { items: [invoice], intake_enabled: false, automatic_execution_enabled: false,
      live_execution_enabled: false, execution_mode: 'simulated', no_action: null };
    const html = renderToStaticMarkup(createElement(InvoiceActivity, { data }));
    assert.match(html, /SIMULATED · no broadcast/);
    assert.doesNotMatch(html, /href=|<strong>Extracted|<strong>Checked|<strong>Verified/);
    const scores = renderToStaticMarkup(createElement(InvoiceScoreboard, { report: {
      ...report, generated_cases: [{ id: 'synthetic-1', category: 'Injection', text: '<script>attack</script>' }],
    } }));
    assert.match(scores, /Synthetic attempts/); assert.match(scores, /not live authorization/);
    assert.match(scores, /Unknown/);
    assert.match(scores, /View generated input/);
    assert.match(scores, /&lt;script&gt;/);
    assert.doesNotMatch(scores, /<script>/);
    const page = renderToStaticMarkup(createElement(InvoicesView, { refreshRevision: 0 }));
    assert.match(page, /Proposer required/); assert.match(page, /Policy administrator/);
    assert.match(page, /Drop an invoice here/);
    assert.match(page, /Choose file/);
    assert.match(page, /Process invoice/);
    assert.doesNotMatch(page, /no-action items|Run watcher pass is not read-only/);
    assert.match(page, /disabled/);
    assert.doesNotMatch(page, /Activate live|Enable live/);
  } finally { await server.close(); }
});

test('file selection rejects unsupported, empty and oversized documents', () => {
  assert.equal(invoiceFileError({name: 'invoice.TXT', size: 100}), null);
  assert.equal(invoiceFileError({name: 'invoice.pdf', size: 1_000_000}), null);
  assert.equal(invoiceFileError({name: 'invoice.EML', size: 1000}), null);
  assert.match(invoiceFileError({name: 'invoice.png', size: 100})!, /TXT/);
  assert.match(invoiceFileError({name: 'invoice.pdf', size: 0})!, /empty/);
  assert.match(invoiceFileError({name: 'invoice.pdf', size: 1_000_001})!, /1 MB/);
});

test('invoice details expose actual Horizon and Bastion review evidence', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
  try {
    const { InvoiceActivity } = await server.ssrLoadModule('/src/views/InvoicesView.tsx');
    const reviewed: Invoice = { ...invoice, state: 'NEEDS_HUMAN_REVIEW',
      execution_mode: null, proposal_status: null, reason: 'LEARNED_REVIEW',
      transaction_hash: null, explorer_url: null,
      checks: { first_stop: 'screening', reasons: [{layer: 'screening', code: 'LEARNED_REVIEW'}],
        without_layer: {}, screening: {classification: 'REVIEW', reason: 'model_disagreement', windows: 2,
          horizon: {status: 'ready', score: .9, version: 'h'},
          bastion: {status: 'ready', score: .01, version: 'b'} } } };
    const html = renderToStaticMarkup(createElement(InvoiceActivity, {data: {
      items: [reviewed], intake_enabled: true, automatic_execution_enabled: true,
      live_execution_enabled: false, execution_mode: 'simulated', no_action: null,
    }}));
    assert.match(html, /Horizon \+ Bastion/);
    assert.match(html, /Needs review/);
    assert.match(html, /model_disagreement/);
    assert.match(html, /0\.9000/);
    assert.match(html, /0\.0100/);
    assert.doesNotMatch(html, /href=/);
  } finally { await server.close(); }
});
