import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, Droplets } from 'lucide-react';
import { api } from '../api/client.ts';
import { useRole } from '../useCredentials.ts';
import { fundingExplorer, fundingMessage } from '../funding.ts';
import type { FundingRequest, FundingStatus } from '../funding.ts';
import { weiToEth } from '../amounts.ts';

export function FundingEvidence({ request }: { request: FundingRequest }) {
  const explorer = fundingExplorer(request);
  return <div className="funding-evidence" role="status">
    <strong>{fundingMessage(request)}</strong>
    {request.amount_wei && request.state === 'CONFIRMED' && <p>{weiToEth(request.amount_wei)} ETH received</p>}
    {request.reason && <p>{request.reason}</p>}
    {explorer && <a href={explorer} target="_blank" rel="noopener noreferrer">View on Etherscan <ArrowUpRight size={14} /></a>}
  </div>;
}

export function FundingDialog({ onClose, onFunded }: { onClose: () => void; onFunded: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const active = useRef(true);
  const allowed = useRole('proposer');
  const [status, setStatus] = useState<FundingStatus | null>(null);
  const [prompt, setPrompt] = useState('Fund my wallet with Sepolia test ETH.');
  const [address, setAddress] = useState('');
  const [request, setRequest] = useState<FundingRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inProgress = !!request && ['REQUESTING', 'SUBMITTED', 'UNCERTAIN'].includes(request.state);
  const requestId = request?.id;
  const requestState = request?.state;
  useEffect(() => {
    if (requestState !== 'SUBMITTED' || !requestId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 120000;
    const check = async () => {
      try {
        const result = await api.getFundingRequest(requestId);
        if (cancelled) return;
        setRequest(result);
        if (result.state === 'CONFIRMED') onFunded();
        if (result.state === 'SUBMITTED' && Date.now() < deadline) timer = setTimeout(check, 3000);
      } catch { if (!cancelled) setError('Receipt check unavailable. Use Check status to retry.'); }
    };
    timer = setTimeout(check, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [requestId, requestState, onFunded]);
  useEffect(() => {
    active.current = true;
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.showModal();
    api.getFunding().then(data => {
      if (!active.current) return;
      setStatus(data);
      // No implicit wallet choice, even when only one exists.
    }).catch(() => { if (active.current) setError('Could not load wallets. Close and retry.'); });
    return () => { active.current = false; document.body.style.overflow = overflow; opener?.focus(); };
  }, []);
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await action(); }
    catch (e) { if (active.current) setError(e instanceof Error ? e.message : 'Request failed.'); }
    finally { if (active.current) setBusy(false); }
  };
  return createPortal(<dialog ref={dialog} className="funding-dialog" aria-labelledby="funding-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><h2 id="funding-title"><Droplets size={21} /> Fund wallet</h2><p>Receive test ETH on Ethereum Sepolia.</p></div>
      <button className="btn btn-outline" disabled={busy} onClick={onClose}>Close</button></header>
    <div className="funding-body">
      <span className="funding-mode">{!status ? 'Testnet only · Ethereum Sepolia' : status.mode === 'sepolia' ? 'Sepolia faucet · chain 11155111' : 'Simulation · no on-chain funding'}</span>
      {!status && !error && <p role="status">Loading configured wallets…</p>}
      {status?.unavailable_reason && <p className="required-role-note">{status.unavailable_reason}</p>}
      {!allowed && <p>Proposer required. Connect using Switch role.</p>}
      {status && !status.wallets.length && <p>Which wallet should I fund? Add a public address to WATCHED_ADDRESSES in backend configuration, then restart. Never enter a private key.</p>}
      <form onSubmit={event => { event.preventDefault(); void run(async () => {
        const plan = await api.planFunding(prompt, address || undefined);
        if ('id' in plan) setRequest(plan); else setError(plan.message);
      }); }}>
        <label htmlFor="funding-prompt">What would you like to do?</label>
        <textarea id="funding-prompt" value={prompt} maxLength={500} required rows={2}
          disabled={busy || inProgress} onChange={e => { setPrompt(e.target.value); setRequest(null); }} />
        <label htmlFor="funding-wallet">Wallet to fund</label>
        <select id="funding-wallet" required value={address} disabled={busy || inProgress}
          onChange={e => { setAddress(e.target.value); setRequest(null); }}>
          <option value="">Choose a wallet</option>
          {status?.wallets.map(wallet => <option key={wallet.address} value={wallet.address}>{wallet.label} · {wallet.address.slice(0, 8)}…{wallet.address.slice(-6)}</option>)}
        </select>
        {address && <p className="funding-address">{address}</p>}
        {!request && <button className="btn btn-primary" disabled={busy || !allowed || !status || !status.wallets.length || !!status.unavailable_reason}>
          {busy ? 'Understanding request…' : 'Review request'}</button>}
      </form>
      {request && <>
        <FundingEvidence request={request} />
        {request.state === 'PREPARED' && <div className="funding-confirm">
          <p>The faucet sets the amount. No funds leave your wallet. {request.mode === 'simulated' ? 'This request will be simulated.' : 'This contacts Coinbase’s faucet and shares the selected public address.'}</p>
          <button className="btn btn-primary" disabled={busy || !allowed} onClick={() => void run(async () => {
            const result = await api.requestFunding(request.id); if (active.current) setRequest(result);
          })}>{busy ? 'Requesting…' : request.mode === 'simulated' ? 'Simulate funding' : 'Request test ETH'}</button>
        </div>}
        {['REQUESTING', 'SUBMITTED', 'UNCERTAIN'].includes(request.state) && <button className="btn btn-outline" disabled={busy} onClick={() => void run(async () => {
          const result = await api.getFundingRequest(request.id); if (active.current) { setRequest(result); if (result.state === 'CONFIRMED') onFunded(); }
        })}>{busy ? 'Checking receipt…' : 'Check status'}</button>}
      </>}
      {error && <p role="alert">{error}</p>}
      {!!status?.requests.length && <details className="funding-history"><summary>Earlier requests ({status.requests.length})</summary>
        {status.requests.map(item => <article key={item.id}><small>{new Date(item.created_at).toLocaleString()} · {item.address.slice(0, 8)}…{item.address.slice(-6)}</small>
          <FundingEvidence request={item} />
          {['REQUESTING', 'SUBMITTED', 'UNCERTAIN'].includes(item.state) && <button className="btn btn-outline" disabled={busy} onClick={() => void run(async () => {
            const result = await api.getFundingRequest(item.id); if (active.current) setRequest(result);
          })}>Check status</button>}</article>)}</details>}
    </div>
  </dialog>, document.body);
}
