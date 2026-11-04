import { ArrowUpRight, Check, ChevronRight, Circle, Clock3, Play, ShieldCheck, Wallet } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { api } from '../api/client.ts';
import { weiToEth } from '../amounts.ts';
import { autonomyRequest, readableReason, goalSubmission, autonomyStepState, transactionLinks, type AutonomyWallet, type PendingGoal, type AutonomySnapshot } from '../autonomy.ts';
import './autonomy.css';
import { vaultReady, vaultRequest } from '../vault.ts';

export function AutonomyView() {
  const roles = useSyncExternalStore(api.subscribeCredentials, api.getConnectedRoles, api.getServerConnectedRoles);
  const [snapshot, setSnapshot] = useState<AutonomySnapshot | null>(null);
  const [goal, setGoal] = useState('Fund my wallet if needed, then pay 10 wei to supplier Acme and verify.');
  const [notice, setNotice] = useState('');
  const [showBoundary, setShowBoundary] = useState(false);
  const [walletRevision, setWalletRevision] = useState(0);
  const [refreshError, setRefreshError] = useState('');
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [wallet, setWallet] = useState<AutonomyWallet | null>(null);
  const [walletError, setWalletError] = useState('');
  const isSepolia = snapshot?.mode === 'SEPOLIA';
  const isMainWallet = snapshot?.wallet_source === 'existing-main';
  const supplierName = snapshot?.mandate?.supplier;
  const editedGoal = useRef(false);
  const inFlight = useRef(false);
  const pendingGoal = useRef<PendingGoal | null>(null);
  const vaultControlKey = useRef<{kind: string; key: string} | null>(null);
  async function controlVault(kind: 'PAUSE' | 'OWNER_PAUSE' | 'RESUME' | 'CONFIGURE') {
    if (!vaultControlKey.current || vaultControlKey.current.kind !== kind) {
      vaultControlKey.current = {kind, key: `vault_${kind}_${crypto.randomUUID()}`};
    }
    const role = kind === 'PAUSE' ? 'proposer' : 'policyAdmin';
    const op = await vaultRequest<{id: string}>(kind === 'PAUSE' ? '/pause' : '/owner-intents', role,
      {kind, request_key: vaultControlKey.current.key});
    await vaultRequest(`/operations/${op.id}/execute`, role, null);
    // Keep the same key on uncertain responses; never create a replacement operation.
    vaultControlKey.current = null;
  }
  const refresh = useCallback(async () => {
    if (!roles.includes('proposer') || inFlight.current) return;
    inFlight.current = true;
    try { setSnapshot(await autonomyRequest<AutonomySnapshot>('/snapshot')); setNow(Date.now()); setRefreshError(''); }
    catch { setRefreshError('Task status could not be refreshed. Retrying automatically.'); }
    finally { inFlight.current = false; }
  }, [roles]);
  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => { if (mounted) void refresh(); });
    const timer = setInterval(() => { void refresh(); }, 1500);
    return () => { mounted = false; clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    if (supplierName && !editedGoal.current) {
      setGoal(`Fund my wallet if needed, then pay ${isMainWallet ? '0.00001 ETH' : '10 wei'} to supplier ${supplierName} and verify.`);
    }
  }, [supplierName, isMainWallet]);
  useEffect(() => {
    if (!isSepolia || !roles.includes('proposer')) return;
    let active = true;
    let reading = false;
    const load = async () => {
      if (reading) return;
      reading = true;
      try {
        const value = await autonomyRequest<AutonomyWallet>('/wallet');
        if (active) { setWallet(value); setWalletError(''); }
      } catch { if (active) setWalletError('Sepolia balance unavailable. Check the configured connection.'); }
      finally { reading = false; }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => { active = false; clearInterval(timer); };
  }, [isSepolia, roles, walletRevision]);
  async function act(work: () => Promise<unknown>, message: string) {
    setBusy(true);
    try { await work(); setNotice(message); setWalletRevision(value => value + 1); await refresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : 'The action failed.'); }
    finally { setBusy(false); }
  }
  const connected = roles.includes('proposer');
  const vault = wallet?.vault?.enabled ? wallet.vault : undefined;
  const chain = vault?.chain;
  const expired = !!chain && chain.expires * 1000 <= now;
  const issues = snapshot?.issues.filter(issue => !issue.resolved) ?? [];
  const admin = roles.includes('policyAdmin');
  const quarantined = !!snapshot?.control.quarantined;
  const blocked = quarantined ? 'An administrator needs to review the automation pause.'
    : walletError ? 'Wallet balance unavailable. Retrying…'
    : isSepolia && wallet && !wallet.payments_enabled ? 'Payments need administrator setup.'
    : isSepolia && wallet?.new_task_backend === 'VAULT' && !vaultReady(vault, now)
      ? expired ? 'An administrator can renew the vault session.'
        : chain?.paused ? 'The vault session is paused.' : 'The vault needs an active, funded session.'
      : '';
  const mandate = snapshot?.mandate;
  const startDisabled = busy || !connected || !mandate || !!blocked || (isSepolia && !wallet);
  const receipt = isSepolia && snapshot?.tasks
    .filter(task => task.state === 'COMPLETED' && task.payment_backend === 'VAULT')
    .flatMap(task => transactionLinks({ ...task, events: [], steps: task.steps.filter(step => step.tool === 'payment' || step.tool === 'receipt') }))[0];
  const short = (value: string) => `${value.slice(0, 8)}…${value.slice(-6)}`;
  return <section className="autonomy-main" aria-label="Autonomous tasks workspace">
    {!connected ? <div className="autonomy-card autonomy-empty">
      <Wallet size={20} aria-hidden="true" /><div><h2>Connect to Autonomous Tasks</h2>
      <p>Use <strong>API key</strong> to connect your Proposer role.</p></div>
    </div> : <>
      {isSepolia && <section className="autonomy-card autonomy-overview" aria-label="Wallet and vault">
        <div className="autonomy-overview-grid">
          <div className="autonomy-account">
            <div className="autonomy-card-heading"><h2><Wallet size={17} aria-hidden="true" /> Wallet</h2><span className="autonomy-badge">{wallet && walletError ? 'Last known balance' : 'Sepolia'}</span></div>
            {wallet ? <>
              <div className="autonomy-value" title={weiToEth(wallet.balance_wei) + ' ETH'}>{weiToEth(wallet.balance_wei)} <span>ETH</span></div>
              <a className="autonomy-address" href={`https://sepolia.etherscan.io/address/${wallet.address}`} title={wallet.address} target="_blank" rel="noopener noreferrer">{short(wallet.address)} <ArrowUpRight size={13} aria-hidden="true" /></a>
            </> : <p className="autonomy-muted">{walletError ? 'Balance unavailable' : 'Reading balance…'}</p>}
          </div>
          {vault && <div className="autonomy-account">
            <div className="autonomy-card-heading"><h2><ShieldCheck size={17} aria-hidden="true" /> Guarded vault</h2>
              {chain && <span className="autonomy-badge" data-tone={chain.paused || expired ? 'attention' : 'positive'}>{chain.paused ? 'Paused' : expired ? 'Renewal due' : 'Session active'}</span>}
            </div>
            {chain ? <div className="autonomy-vault-values">
              <div><span>Allowance</span><strong>{weiToEth(chain.remaining)} <small>ETH</small></strong></div>
              <div><span>Escrow</span><strong>{weiToEth(chain.balance)} <small>ETH</small></strong></div>
            </div> : <p className="autonomy-muted">{vault.address ? 'Reading session…' : 'Awaiting setup'}</p>}
          </div>}
        </div>
        {wallet && <details className="autonomy-disclosure">
          <summary><ChevronRight size={15} aria-hidden="true" /> Wallet & session details</summary>
          <div className="autonomy-detail-body">
            <dl className="autonomy-facts">
              <div><dt>Wallet</dt><dd className="font-mono">{wallet.address}</dd></div>
              {vault?.address && <div><dt>Vault</dt><dd><a href={`https://sepolia.etherscan.io/address/${vault.address}`} target="_blank" rel="noopener noreferrer">{vault.address}</a></dd></div>}
              {vault?.agent && <div><dt>Restricted agent</dt><dd className="font-mono">{vault.agent}</dd></div>}
              {chain && <div><dt>Session expiry</dt><dd>{new Date(chain.expires * 1000).toLocaleString()} · Epoch {vault?.epoch}</dd></div>}
              <div><dt>Payment fee ceiling</dt><dd>{weiToEth(wallet.max_payment_fee_wei)} ETH</dd></div>
              <div><dt>Automatic funding</dt><dd>{wallet.faucet_enabled ? 'Configured' : 'Setup required'}</dd></div>
              {wallet.incoming_watch?.enabled && <div><dt>Incoming monitor</dt><dd>{wallet.incoming_watch.suspended_epoch != null ? 'Paused for review' : wallet.incoming_watch.block == null ? 'Starting' : `Block ${wallet.incoming_watch.block}`}</dd></div>}
            </dl>
            {chain && <div className="autonomy-actions">
              {!chain.paused && connected && <button className="btn btn-outline" disabled={busy || BigInt(chain.agent_balance) === 0n}
                onClick={() => void act(() => controlVault('PAUSE'), 'Vault pause submitted.')}>Pause vault</button>}
              {!chain.paused && admin && <button className="btn btn-outline" disabled={busy}
                onClick={() => void act(() => controlVault('OWNER_PAUSE'), 'Owner pause submitted.')}>Pause as administrator</button>}
              {chain.paused && <button className="btn btn-outline" disabled={busy || !admin}
                onClick={() => void act(() => controlVault('RESUME'), 'Vault resume submitted.')}>Resume as administrator</button>}
              {expired && <button className="btn btn-outline" disabled={busy || !admin}
                onClick={() => void act(() => controlVault('CONFIGURE'), 'Session renewal submitted.')}>Renew session</button>}
            </div>}
            {!!vault?.operations?.length && <ul className="autonomy-operations">{vault.operations.slice(0, 3).map(op =>
              <li key={op.id}><span>{readableReason(op.kind)} · {readableReason(op.status)}</span>
                {op.tx_hash && <a href={`https://sepolia.etherscan.io/tx/${op.tx_hash}`} target="_blank" rel="noopener noreferrer">Transaction <ArrowUpRight size={13} aria-hidden="true" /></a>}</li>)}</ul>}
          </div>
        </details>}
      </section>}
      <form className="autonomy-card autonomy-goal" onSubmit={event => {event.preventDefault(); if (startDisabled) return; void act(
        async () => {
          pendingGoal.current = goalSubmission(pendingGoal.current, goal);
          const result = await autonomyRequest('/goals', 'proposer', {goal, request_key: pendingGoal.current.key});
          pendingGoal.current = null;
          return result;
        }, 'Task started.');}}>
        <div className="autonomy-card-heading"><label htmlFor="autonomous-goal">New task</label>
          {snapshot && <span className="autonomy-badge">{isSepolia ? 'Local Gemma' : 'Simulation'}</span>}</div>
        <div className="autonomy-compose"><textarea id="autonomous-goal" rows={2} value={goal} onChange={e => {editedGoal.current = true; setGoal(e.target.value);}} maxLength={500} required />
          <button className="btn btn-primary" disabled={startDisabled}><Play size={15} aria-hidden="true" /> Start task</button></div>
        {mandate && <div className="autonomy-actions autonomy-demo-actions">
          <button type="button" className="btn btn-outline" disabled={busy} onClick={() => {
            editedGoal.current = true;
            const amount = Math.min(mandate.payment_cap, isMainWallet ? 10_000_000_000_000 : 10);
            setGoal(`Fund my wallet if needed, then pay ${amount} wei to supplier ${mandate.supplier} and verify.`);
            setShowBoundary(false);
          }}>Use payment example</button>
          <button type="button" className="btn btn-outline" aria-expanded={showBoundary}
            aria-controls="autonomy-boundary-example" onClick={() => setShowBoundary(value => !value)}>Show spending boundary</button>
          {receipt && <a className="autonomy-address" href={receipt.url} target="_blank" rel="noopener noreferrer">
            Last verified vault payment <ArrowUpRight size={13} aria-hidden="true" />
          </a>}
        </div>}
        <div id="autonomy-boundary-example" hidden={!showBoundary || !mandate}>
          {mandate && <p className="autonomy-muted">
            <strong>Would be blocked.</strong> A request for {weiToEth(String(mandate.payment_cap + 1))} ETH
            exceeds the standing mandate limit of {weiToEth(String(mandate.payment_cap))} ETH.
            This preview reads the saved mandate.
          </p>}
        </div>
        {blocked && <div className="autonomy-notice"><span>{blocked}</span>
          {quarantined && <a href="#autonomy-controls">Review controls</a>}
          {expired && admin && <button className="btn btn-outline" type="button" disabled={busy}
            onClick={() => void act(() => controlVault('CONFIGURE'), 'Session renewal submitted.')}>Renew session</button>}
        </div>}
        {snapshot && !mandate && <p className="autonomy-muted">Set a standing mandate in Controls to start a task.</p>}
        {(refreshError || notice) && <p className="autonomy-muted" role="status">{refreshError || notice}</p>}
      </form>
      <div className="autonomy-columns">
        <section className="autonomy-card autonomy-ledger" aria-labelledby="autonomy-timeline">
          <div className="autonomy-card-heading autonomy-section-head"><h2 id="autonomy-timeline">Task timeline</h2>
            {snapshot && <span className="autonomy-muted">{snapshot.tasks.length} {snapshot.tasks.length === 1 ? 'task' : 'tasks'}</span>}</div>
          {!snapshot?.tasks.length && <p className="autonomy-empty-text">{snapshot ? 'No tasks yet.' : 'Loading tasks…'}</p>}
          {snapshot?.tasks.map(task => <article className="autonomy-task" key={task.id}>
            <div className="autonomy-card-heading"><div><h3>{weiToEth(String(task.amount))} ETH</h3><span className="autonomy-muted">{task.payment_backend === 'VAULT' ? 'Guarded vault payment' : 'Supplier payment'}</span></div>
              <span className="autonomy-badge" data-tone={task.state === 'COMPLETED' ? 'positive' : task.reason ? 'attention' : undefined}>{readableReason(task.state)}</span></div>
            <ol className="autonomy-steps">{['Balance', 'Funding', 'Payment', 'Verification'].map((name, index) => {
              const step = task.steps[index];
              const state = autonomyStepState(task.state, step?.state);
              let skipped = false;
              if (index === 1 && state === 'COMPLETED' && step?.result) {
                try { skipped = JSON.parse(step.result)?.skipped === true; } catch { /* Keep the recorded status. */ }
              }
              const Icon = state === 'COMPLETED' ? Check : ['RUNNING', 'WAITING'].includes(state) ? Clock3 : Circle;
              return <li key={name} data-state={state}><Icon size={14} aria-hidden="true" /><div>{name}<small>{skipped ? 'Not needed' : readableReason(state)}</small></div></li>;
            })}</ol>
            {task.reason && <p className="autonomy-muted">{readableReason(task.reason)}</p>}
            {(task.state === 'HUMAN_REQUIRED' || task.state === 'WAITING_APPROVAL') && <div className="autonomy-actions">
              {isSepolia && task.state === 'HUMAN_REQUIRED' && <button className="btn btn-outline" disabled={busy || !connected}
                onClick={() => void act(() => autonomyRequest(`/goals/${task.id}/reconcile`, 'proposer', {}), 'Existing receipt checked.')}>Check receipt</button>}
              {isMainWallet && task.state === 'HUMAN_REQUIRED' && ['RECONCILIATION_UNAVAILABLE', 'PREFLIGHT_UNAVAILABLE', 'PREFLIGHT_LIMIT_BLOCK'].includes(task.reason || '') &&
                <button className="btn btn-outline" disabled={busy || !admin}
                  onClick={() => void act(() => autonomyRequest(`/goals/${task.id}/resume-before-signing`, 'policyAdmin', {}), 'Recovery requested for the same proposal.')}>Retry before signing</button>}
              {task.state === 'WAITING_APPROVAL' && (['APPROVE', 'REJECT'] as const).map(decision => <button className="btn btn-outline" key={decision}
                disabled={busy || !roles.includes('approver')}
                onClick={() => void act(() => autonomyRequest(`/approvals/${task.id}/decision`, 'approver', {decision}), 'Decision recorded.')}>{decision === 'APPROVE' ? 'Approve' : 'Reject'}</button>)}
            </div>}
            <div className="autonomy-task-links">{transactionLinks(task).map(link =>
              <a key={link.hash} href={link.url} title={link.hash} target="_blank" rel="noopener noreferrer">Transaction <span className="font-mono">{short(link.hash)}</span><ArrowUpRight size={13} aria-hidden="true" /></a>)}</div>
            <details className="autonomy-disclosure"><summary><ChevronRight size={15} aria-hidden="true" /> Task details <span>{task.events.length} events</span></summary>
              <div className="autonomy-detail-body"><p className="autonomy-muted">Payment limit {weiToEth(String(task.payment_cap))} ETH · Funding limit {weiToEth(String(task.funding_cap))} ETH</p>
                {task.events.map(event => <p className="autonomy-event" key={event.id}><strong>{readableReason(event.kind)}</strong> · {event.detail}</p>)}</div>
            </details>
          </article>)}
        </section>
        <aside className="autonomy-card autonomy-controls" id="autonomy-controls" aria-labelledby="autonomy-controls-title">
          <div className="autonomy-card-heading autonomy-section-head"><h2 id="autonomy-controls-title">Controls</h2></div>
          {quarantined && <div className="autonomy-inbox"><strong>Automation paused</strong><button className="btn btn-outline" disabled={busy || !admin}
            onClick={() => void act(() => autonomyRequest('/quarantine/resume', 'policyAdmin', {}), 'Automation resumed.')}>Resume as administrator</button></div>}
          <div className="autonomy-inbox"><strong>Exceptions</strong><span className="autonomy-muted">{snapshot ? issues.length ? `${issues.length} open` : 'All clear' : 'Loading…'}</span></div>
          {issues.map(issue => <div className="autonomy-issue" key={issue.id}><strong>{readableReason(issue.reason)}</strong>
            {issue.task_id && <span className="autonomy-muted">Task {issue.task_id.slice(0, 8)}</span>}</div>)}
          {!!snapshot?.system_events?.length && <details className="autonomy-disclosure"><summary><ChevronRight size={15} aria-hidden="true" /> System activity</summary>
            <div className="autonomy-detail-body">{snapshot.system_events.map(event => <p className="autonomy-event" key={event.id}>{readableReason(event.kind)} · {event.detail}</p>)}</div>
          </details>}
      <details className="autonomy-mandate"><summary><ChevronRight size={15} aria-hidden="true" /> Standing mandate</summary>
        <form key={`${snapshot?.mandate?.version || 0}-${wallet?.approval_threshold_wei || ''}`} onSubmit={event => {event.preventDefault(); const form = new FormData(event.currentTarget);
          void act(() => autonomyRequest('/mandate', 'policyAdmin', {supplier: form.get('supplier'), recipient: form.get('recipient'),
            payment_cap: Number(form.get('payment')), funding_cap: form.get('funding'),
            approval_threshold: form.get('threshold')}, 'PUT'), 'Administrator mandate saved.');}}>
          <label>Supplier<input name="supplier" defaultValue={snapshot?.mandate?.supplier || wallet?.supplier || 'Acme'} required /></label>
          <label>Recipient<input name="recipient" defaultValue={snapshot?.mandate?.recipient || wallet?.recipient || (isSepolia ? '' : '0x' + '1'.repeat(40))} placeholder={isSepolia ? 'Administrator-configured recipient' : undefined} required /></label>
          <label>Session payment budget (wei)<input name="payment" type="number" min="1" max="1000000000000000" defaultValue={snapshot?.mandate?.payment_cap || '1000'} required /></label>
          <label>Funding budget (wei)<input name="funding" inputMode="numeric" pattern="[0-9]+" defaultValue={snapshot?.mandate?.funding_cap || (isSepolia ? '0' : '1000')} required /></label>
          <label>Human approval at (wei)<input name="threshold" inputMode="numeric" pattern="[0-9]+" defaultValue={wallet?.approval_threshold_wei || '50'} readOnly={wallet?.policy_managed} required /></label>
          <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}>Save mandate</button>
          <p>{isMainWallet ? 'Changes stay within your wallet policy and vendor limits.' : 'Changing the mandate puts earlier tasks on hold.'}</p>
        </form></details>
        </aside>
      </div>
    </>}
  </section>;
}
