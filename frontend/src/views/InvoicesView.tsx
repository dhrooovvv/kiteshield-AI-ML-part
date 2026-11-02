import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Upload, FileText, X, ArrowUpRight } from 'lucide-react';
import { api, KiteShieldAPIError } from '../api/client.ts';
import { useConnectedRoles } from '../useCredentials.ts';
import { ethToWei, weiToEth } from '../amounts.ts';
import { counterfactualLabel, invoiceEventLabel, invoiceExplorer, invoiceIsSimulated, redTeamCounts, invoiceFileError, invoiceReasonLabel } from '../invoices.ts';
import type { InvoiceSnapshot, InvoiceVendor, InvoiceRedTeam } from '../invoices.ts';

export function InvoiceActivity({ data, onRecheck, canRecheck = false, busy = false }: { data: InvoiceSnapshot; onRecheck?: (id: string) => void; canRecheck?: boolean; busy?: boolean }) {
  return <section className="ap-section ap-activity" aria-labelledby="ap-activity">
    <div className="ap-heading"><h2 id="ap-activity">Recent invoices</h2><span>{data.items.length} invoices</span></div>
    {!data.items.length ? <p className="ap-empty">Your invoices will appear here after processing.</p> :
      <div className="ap-table-wrap"><table><thead><tr><th scope="col">Invoice</th><th scope="col">Amount</th><th scope="col">Status</th><th scope="col">Details</th></tr></thead>
        <tbody>{data.items.map(invoice => {
          const simulated = invoiceIsSimulated(invoice);
          const explorer = invoiceExplorer(invoice);
          const state = simulated ? 'Simulated' : ({ PAID: 'Submitted', VERIFIED: 'Confirmed', NEEDS_HUMAN_REVIEW: 'Needs review', CHECKED: 'Checked', EXECUTING: 'Processing', OBSERVED: 'Processing', BLOCKED: 'Blocked', REVERTED: 'Reverted', UNCERTAIN: 'Uncertain' }[invoice.state] ?? invoice.state);
          return <tr key={invoice.id}><td><strong>{invoice.extraction?.invoice_number ?? (['BLOCKED', 'NEEDS_HUMAN_REVIEW'].includes(invoice.state) ? 'Unparsed invoice' : 'Reading invoice')}</strong><small>{invoice.extraction?.vendor_name ?? invoice.vendor_id ?? 'Vendor unavailable'}</small></td>
            <td className="ap-amount">{invoice.extraction ? `${invoice.extraction.amount_eth} ETH` : 'Unavailable'}</td>
            <td><span className={`ap-state ${simulated || invoice.state === 'VERIFIED' ? 'ap-state-ok' : ''}`}>{state}</span>
              {simulated && <small>No funds sent</small>}
              {['BLOCKED', 'NEEDS_HUMAN_REVIEW', 'UNCERTAIN', 'REVERTED'].includes(invoice.state) && <small>{invoiceReasonLabel(invoice.reason)}</small>}
              {explorer && <a className="ap-tx-link" href={explorer} target="_blank" rel="noopener noreferrer">Transaction <ArrowUpRight size={13} /></a>}</td>
            <td>{!explorer && !simulated && ['CHECKED', 'BLOCKED', 'NEEDS_HUMAN_REVIEW'].includes(invoice.state) && <small>Not submitted · no transaction link</small>}
              {invoice.can_recheck === true && <><button className="btn btn-outline ap-recheck" disabled={!canRecheck || busy || !onRecheck} title={!canRecheck ? 'Proposer required to recheck eligibility.' : 'Reruns screening, extraction, vendor and current policy checks. Existing execution permissions still apply.'} onClick={() => onRecheck?.(invoice.id)}>Recheck eligibility</button><small>{data.automatic_execution_enabled && data.live_execution_enabled ? 'May pay within approved limits.' : 'Automatic payments are off.'}</small></>}
              <details className="ap-record-details"><summary>View details</summary>
              <p>Invoice: {invoice.id}<br />Document hash: {invoice.document_hash}<br />Proposal: {invoice.proposal_id ?? 'None'}<br />Due: {invoice.extraction?.due_date ?? 'Unavailable'}<br />Latency: {invoice.latency_ms === null ? 'Unavailable' : `${invoice.latency_ms} ms`}</p>
              {simulated && <p>SIMULATED · no broadcast</p>}
              {invoice.state === 'PAID' && <p>Submitted, not confirmed. Waiting for a matching receipt.</p>}
              {invoice.reason && <p>{invoice.reason}</p>}
              {invoice.checks && <div><strong>Checks</strong>{invoice.checks.reasons.map((reason, i) => <p key={i}>{reason.layer}: {reason.code}</p>)}</div>}
              {invoice.checks?.screening && <div><strong>Horizon + Bastion</strong><p>{invoice.checks.screening.classification} · {invoice.checks.screening.reason}</p>
                <p>Horizon: {invoice.checks.screening.horizon?.status ?? 'not run'}{typeof invoice.checks.screening.horizon?.score === 'number' && Number.isFinite(invoice.checks.screening.horizon.score) && ` · score ${invoice.checks.screening.horizon.score.toFixed(4)}`}<br />Bastion: {invoice.checks.screening.bastion?.status ?? 'not run'}{typeof invoice.checks.screening.bastion?.score === 'number' && Number.isFinite(invoice.checks.screening.bastion.score) && ` · score ${invoice.checks.screening.bastion.score.toFixed(4)}`}</p>
                {invoice.checks.screening.windows !== undefined && <p>{invoice.checks.screening.windows} text windows checked.</p>}</div>}
              <ol className="ap-events">{invoice.events.map((event, i) => <li key={i}><strong>{simulated && ['paid', 'submitted', 'verified'].includes(event.stage.toLowerCase()) ? `${event.stage} · simulation only, no broadcast` : invoiceEventLabel(event.stage)}</strong><time dateTime={event.at}>{new Date(event.at).toLocaleString()}</time>{event.reason && <span>{event.reason}</span>}</li>)}</ol>
            </details></td></tr>;
        })}</tbody></table></div>}
  </section>;
}

export function InvoiceScoreboard({ report }: { report: InvoiceRedTeam }) {
  if (!report.available || report.simulation_only !== true) return <p>Offline red-team report unavailable.</p>;
  const counts = redTeamCounts(report);
  return <><p>Synthetic attempts · simulation only. Counterfactuals describe removed checks; they are not live authorization.</p>
    <p className="ap-score">{counts.attempts} attempts · {counts.stopped} recorded first stops · {counts.wouldPass} counterfactuals would pass checks · {counts.unknown} unknown</p>
    {!report.attempts.length ? <p>No synthetic attempts in this report.</p> : <div className="ap-table-wrap"><table><thead><tr><th scope="col">Synthetic attempt</th><th scope="col">First stop / reasons</th><th scope="col">Without each layer</th></tr></thead>
      <tbody>{report.attempts.map(attempt => <tr key={attempt.id}><td><strong>{attempt.category}</strong><br />{attempt.id}
        {report.generated_cases?.find(input => input.id === attempt.id) && <details><summary>View generated input</summary><pre className="ap-attack-text">{report.generated_cases.find(input => input.id === attempt.id)?.text}</pre></details>}</td>
        <td>{attempt.measurement_valid === false ? 'Not tested · experiment failed' : attempt.first_stop ?? 'No stop recorded'}{attempt.reason && <p>{attempt.reason}</p>}{attempt.reasons.map((reason, i) => <p key={i}>{reason.layer}: {reason.code}</p>)}</td>
        <td>{Object.entries(attempt.without_layer).map(([layer, result]) => <p key={layer}><strong>{layer}: {counterfactualLabel(result)}</strong><br />{result.remaining_reasons.join(', ') || 'No remaining reasons recorded'}</p>)}</td></tr>)}</tbody></table></div>}</>;
}

export function VendorForm({ vendor, allowed, onSaved, create = false, onBusyChange }: { vendor: InvoiceVendor; allowed: boolean; onSaved: () => void; create?: boolean; onBusyChange?: (busy: boolean) => void }) {
  const [id, setId] = useState(vendor.id);
  const [name, setName] = useState(vendor.name);
  const [address, setAddress] = useState(vendor.payout_address);
  const [maximum, setMaximum] = useState(() => create ? '' : weiToEth(vendor.maximum_wei));
  const [active, setActive] = useState(vendor.active);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const validId = /^[a-z][a-z0-9_-]{0,63}$/.test(id);
  return <form className="ap-form" onSubmit={async event => {
    event.preventDefault(); if (!allowed || busy) return;
    setBusy(true); onBusyChange?.(true); setMessage('');
    try {
      if (create && !validId) throw new Error('Use a lowercase vendor ID such as northstar-demo.');
      ethToWei(maximum);
      if (!/^0x[0-9a-fA-F]{40}$/.test(address.trim())) throw new Error('Enter a 40-digit hexadecimal payout address starting with 0x.');
      await api.updateInvoiceVendor(create ? id : vendor.id, { name: name.trim(), payout_address: address.trim(), maximum_eth: maximum, expected_version: vendor.version, active });
      setMessage(create ? 'Vendor added.' : 'Vendor saved.');
      if (create) { setId(''); setName(''); setAddress(''); setMaximum(''); setActive(true); }
      onSaved();
    } catch (error) { setMessage(error instanceof KiteShieldAPIError && error.status === 409
      ? 'Vendor version changed. Refresh, reopen this form, and review the latest values before saving.'
      : error instanceof Error ? error.message : 'Save failed. Refresh and retry.'); }
    finally { setBusy(false); onBusyChange?.(false); }
  }}>
    {!allowed && <p>Connect Policy administrator using Switch role to {create ? 'add' : 'edit'} vendors.</p>}
    {!create && <p>Version {vendor.version}</p>}
    <fieldset disabled={!allowed || busy}>
      {create && <div><label>Vendor ID<input required value={id} onChange={e => setId(e.target.value)} placeholder="northstar-demo" pattern="[a-z][a-z0-9_-]{0,63}" maxLength={64} autoCapitalize="none" spellCheck={false} aria-describedby="ap-vendor-id-help" aria-invalid={!!id && !validId} /></label>
        <small id="ap-vendor-id-help">Lowercase letters, numbers, hyphens or underscores; start with a letter. Example: northstar-demo.</small>
        {!!id && !validId && <p role="alert" className="ap-vendor-id-error">Use an ID like northstar-demo. Enter Northstar Services in Vendor name below.</p>}</div>}
      <label>Vendor name<input required value={name} onChange={e => setName(e.target.value)} placeholder={create ? 'Northstar Services' : undefined} /></label>
      <label>Payout address<input required value={address} onChange={e => setAddress(e.target.value)} spellCheck={false} /></label>
      <label>Maximum per invoice (ETH)<input required inputMode="decimal" value={maximum} onChange={e => setMaximum(e.target.value)} /></label>
      <label className="ap-checkbox"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />Active vendor</label>
      <button className="btn btn-primary" type="submit" disabled={create && !validId}>{busy ? 'Saving…' : create ? 'Add vendor' : 'Save vendor'}</button></fieldset>
    {message && <p role="status">{message}</p>}
  </form>;
}

function VendorDialog({ vendor, create, allowed, onSaved, onClose }: { vendor: InvoiceVendor; create: boolean; allowed: boolean; onSaved: () => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const opener = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const element = dialog.current;
    element?.showModal();
    return () => { element?.close(); document.body.style.overflow = overflow; if (opener instanceof HTMLElement && opener.isConnected) opener.focus(); };
  }, []);
  if (typeof document === 'undefined') return null;
  return createPortal(<dialog ref={dialog} className={`ap-page ap-vendor-dialog ${create ? 'ap-new-vendor' : ''}`} aria-labelledby="ap-vendor-dialog-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <header><div><h2 id="ap-vendor-dialog-title">{create ? 'Add vendor' : 'Edit vendor'}</h2><p>Only policy-allowlisted payout addresses can be saved.</p></div><button className="btn btn-outline" disabled={saving} onClick={onClose}>Close</button></header>
    <div className="ap-vendor-dialog-body"><VendorForm vendor={vendor} create={create} allowed={allowed} onBusyChange={setSaving} onSaved={() => { onSaved(); onClose(); }} /></div>
  </dialog>, document.body);
}

export function VendorRegistry({ vendors, allowed, onSaved }: { vendors: InvoiceVendor[] | null; allowed: boolean; onSaved: () => void }) {
  const [editing, setEditing] = useState<InvoiceVendor | null>(null);
  const [creating, setCreating] = useState(false);
  return <section className="ap-section ap-vendors" aria-labelledby="ap-vendors"><div className="ap-heading"><h2 id="ap-vendors">Approved vendors</h2><span>{vendors ? `${vendors.filter(v => v.active).length} active` : 'Unavailable'}</span></div>
    <button className="btn btn-outline" disabled={!allowed} title={!allowed ? 'Policy administrator required.' : undefined} onClick={() => setCreating(true)}>Add vendor</button>
    {!allowed && <p>Connect Policy administrator to manage vendors.</p>}
    {vendors?.length === 0 && <p>No approved vendors yet.</p>}
    {vendors?.map(vendor => <div className="ap-vendor ap-vendor-row" key={vendor.id}><strong>{vendor.name}</strong><small>Vendor ID: <code>{vendor.id}</code></small><small>{vendor.active ? 'Up to' : 'Inactive ·'} {weiToEth(vendor.maximum_wei)} ETH / invoice</small><p className="ap-vendor-address">{vendor.payout_address}</p><button className="btn btn-outline" disabled={!allowed} onClick={() => setEditing(vendor)} aria-label={`Edit ${vendor.name}`}>Edit</button></div>)}
    {(creating || editing) && <VendorDialog create={creating} vendor={editing ?? { id: '', name: '', payout_address: '', maximum_wei: '0', version: 0, active: true }} allowed={allowed} onSaved={onSaved} onClose={() => { setCreating(false); setEditing(null); }} />}
  </section>;
}

export function InvoicesView({ refreshRevision }: { refreshRevision: number }) {
  const roles = useConnectedRoles();
  const admin = roles.includes('policyAdmin');
  const proposer = roles.includes('proposer');
  const [data, setData] = useState<InvoiceSnapshot | null>(null);
  const [vendors, setVendors] = useState<InvoiceVendor[] | null>(null);
  const [report, setReport] = useState<InvoiceRedTeam | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [mode, setMode] = useState<'file' | 'text'>('file');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [fileError, setFileError] = useState('');
  const picker = useRef<HTMLInputElement>(null);
  const loaded = useRef(false);
  const inFlight = useRef(false);
  useEffect(() => {
    let cancelled = false;
    if (!loaded.current) queueMicrotask(() => { if (!cancelled) setLoading(true); });
    void Promise.allSettled([api.getInvoices(), api.getInvoiceVendors(), api.getInvoiceRedTeam()]).then(([invoices, vendorList, redTeam]) => {
      if (cancelled) return;
      setData(invoices.status === 'fulfilled' ? invoices.value : null);
      setVendors(vendorList.status === 'fulfilled' ? vendorList.value : null);
      setReport(redTeam.status === 'fulfilled' ? redTeam.value : null);
      setErrors([...(invoices.status === 'rejected' ? ['Invoices unavailable. Refresh and check your connection.'] : []),
        ...(vendorList.status === 'rejected' ? ['Vendors unavailable. Refresh to try again.'] : []),
        ...(redTeam.status === 'rejected' ? ['Red-team results unavailable.'] : [])]);
      loaded.current = true;
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [refreshRevision, revision, roles]);
  const disabled = !proposer || !data?.intake_enabled || busy || loading;
  async function run(action: () => Promise<unknown>, success: string, clear = false) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setMessage('');
    try {
      await action(); setMessage(success);
      if (clear) { setFile(null); setText(''); if (picker.current) picker.current.value = ''; }
      setRevision(value => value + 1);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not process invoice. Try again.'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  function selectFiles(files: FileList | File[]) {
    if (disabled) return;
    setFile(null); setFileError(''); setMessage('');
    if (files.length !== 1) { setFileError('Add one invoice at a time.'); return; }
    const error = invoiceFileError(files[0]);
    if (error) { setFileError(error); return; }
    setFile(files[0]);
  }
  return <div className="ap-page">
    <div className="ap-toolbar"><h2>Invoice inbox</h2><button className="btn btn-outline" disabled={loading || busy} onClick={() => setRevision(value => value + 1)}>Refresh invoices</button></div>
    {errors.length > 0 && <div role="alert">{errors.map(error => <p key={error}>{error}</p>)}</div>}
    <div className="ap-shell"><div className="ap-workspace">
      <section className="ap-section ap-upload" aria-labelledby="ap-add-title">
        <div className="ap-heading"><h2 id="ap-add-title">Add an invoice</h2><span>{data?.execution_mode === 'simulated' ? 'Simulation' : data?.execution_mode === 'sepolia' ? 'Sepolia' : 'Connecting'}</span></div>
        <form onSubmit={event => {
          event.preventDefault();
          if (disabled) return;
          if (mode === 'file' && file) void run(() => api.uploadInvoice(file), 'Invoice processed. See the result below.', true);
          if (mode === 'text' && text.trim()) void run(() => api.submitInvoice(text.trim()), 'Invoice processed. See the result below.', true);
        }}>
          {mode === 'file' ? <div className={`ap-dropzone ${dragging ? 'is-dragging' : ''} ${disabled ? 'is-disabled' : ''}`} role="group" aria-label="Invoice upload" onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); selectFiles(event.dataTransfer.files); }}>
            {file ? <><FileText size={28} /><strong>{file.name}</strong><span>{Math.ceil(file.size / 1000)} KB · ready to process</span><button type="button" className="ap-file-remove" disabled={busy} aria-label="Remove selected invoice" onClick={() => { setFile(null); if (picker.current) picker.current.value = ''; }}><X size={16} />Remove</button></> : <><Upload size={28} /><h3>Drop an invoice here</h3><span>TXT, text PDF or EML · up to 1 MB</span><button className="btn btn-outline" type="button" disabled={disabled} onClick={() => picker.current?.click()}>Choose file</button></>}
            <input hidden ref={picker} type="file" accept=".txt,.pdf,.eml" aria-label="Invoice file" disabled={disabled} onChange={event => { if (event.target.files) selectFiles(event.target.files); }} />
          </div> : <label className="ap-text-label">Invoice text<textarea rows={5} required value={text} maxLength={20000} onChange={event => setText(event.target.value)} disabled={disabled} placeholder="Paste the vendor, invoice number, ETH amount and due date…" /></label>}
          {fileError && <p role="alert" className="ap-input-error">{fileError}</p>}
          <div className="ap-upload-actions"><button type="button" className="ap-text-button" disabled={busy} onClick={() => { setMode(mode === 'file' ? 'text' : 'file'); setFileError(''); }}>{mode === 'file' ? 'Paste text instead' : 'Upload a file instead'}</button><button className="btn btn-primary" type="submit" disabled={disabled || (mode === 'file' ? !file : !text.trim())}>{busy ? 'Processing…' : 'Process invoice'}</button></div>
          {!proposer ? <p className="ap-help">Proposer required. Connect using Switch role.</p> : !data?.intake_enabled && !loading ? <p className="ap-help">Invoice intake is off in backend settings.</p> : data?.execution_mode === 'simulated' ? <p className="ap-help">Simulation only. No funds will be sent.</p> : data?.execution_mode === 'sepolia' ? <p className="ap-help">{data.automatic_execution_enabled && data.live_execution_enabled ? 'Eligible invoices may submit Sepolia payments within approved limits.' : 'Sepolia connected · automatic payments disabled. Checked invoices have not been submitted.'}</p> : null}
          {data?.horizon_bastion_enabled && <p className="ap-help">Horizon + Bastion {data.horizon_bastion_evaluated ? 'screening on.' : 'screening requires validation.'}</p>}
          {message && <p role="status" className="ap-feedback">{message}</p>}
        </form>
      </section>
      <VendorRegistry vendors={vendors} allowed={admin && !loading && !busy} onSaved={() => setRevision(value => value + 1)} />
    </div>
    {loading && !data && <p role="status">Loading invoices…</p>}
    {data && <InvoiceActivity data={data} canRecheck={proposer && data.intake_enabled} busy={busy || loading} onRecheck={id => void run(() => api.recheckInvoice(id), 'Eligibility checked again. Current payment permissions still apply.')} />}
    <details className="ap-section ap-secondary"><summary>Red-team results <span>{report?.available ? `${redTeamCounts(report).stopped} of ${report.attempts.length} stopped · simulation` : 'Unavailable'}</span></summary>
      <p>Generated variants may be ineffective. Inspect inputs before interpreting outcomes.</p>{report && <InvoiceScoreboard report={report} />}
    </details>
    {data && <details className="ap-section ap-secondary"><summary>Settings & details</summary>
      <p>Intake {data.intake_enabled ? 'on' : 'off'} · Invoice automation flag {data.automatic_execution_enabled ? 'on' : 'off'} · Live invoice flag {data.live_execution_enabled ? 'on' : 'off'}. Global execution settings and current policy still apply.</p>
      {data.no_action && <p>Last watcher pass: {data.no_action.reason} · {data.no_action.count} no-action passes · {new Date(data.no_action.at).toLocaleString()}</p>}
      <p>Running the watcher may execute eligible invoices. Policy administrator required.</p>
      <button className="btn btn-outline" disabled={!admin || busy || loading} onClick={() => void run(() => api.observeInvoices(), 'Watcher pass completed.')}>Run inbox watcher</button>
    </details>}
    </div>
  </div>;
}
