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
  }, [isSepolia, roles]);
  async function act(work: () => Promise<unknown>, message: string) {
    setBusy(true);
    try { await work(); setNotice(message); await refresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : 'The action failed.'); }
    finally { setBusy(false); }
  }
  return <section className="autonomy-main">
    <div className="autonomy-heading"><div><h2>One goal. Every step accounted for.</h2>
      <p>Local Gemma proposes the plan. Deterministic rules control authority.</p></div>
      <span className="autonomy-label">{isSepolia ? 'Sepolia · on-chain' : snapshot ? 'Isolated simulation' : 'Checking connection'}</span></div>
    <p className="autonomy-boundary">{snapshot?.control.quarantined ? 'Self-quarantined. An administrator must resume execution.' : isSepolia ? `${isMainWallet ? 'Uses your existing wallet and policy.' : 'Uses a separate test wallet.'} Administrator limits and human approvals still apply. A mined receipt confirms each payment.` : 'Works within administrator permissions. No funded wallet access or on-chain broadcasts.'}</p>
    {isSepolia && <div className="autonomy-task">
      <strong>{isMainWallet ? 'Existing Sepolia wallet' : 'Separate Sepolia wallet'}</strong>
      {wallet && <><p style={{overflowWrap: 'anywhere'}}>{wallet.address}</p>
        <p>{weiToEth(wallet.balance_wei)} ETH · {walletError ? 'last known balance' : 'on-chain balance'}</p>
        <p>{wallet.payments_enabled ? `Payment fee ceiling: ${weiToEth(wallet.max_payment_fee_wei)} ETH. Each task reserves a smaller fee after checking the network.` : 'Payments disabled. Configure a recipient and payment and fee budgets in the separate administrator profile, then restart.'}</p>
        <p>{wallet.faucet_enabled ? 'Configured faucet enabled.' : 'Automatic faucet disabled; provider credentials and a funding budget are required.'}</p></>}
      {wallet?.vault?.enabled && <div className="autonomy-vault">
        <strong>Guarded vault · {wallet.new_task_backend === 'VAULT' ? 'used for new tasks' : 'available'}</strong>
        {wallet.vault.address ? <>
          <p style={{overflowWrap: 'anywhere'}}>Vault: <a href={`https://sepolia.etherscan.io/address/${wallet.vault.address}`} target="_blank" rel="noopener noreferrer">{wallet.vault.address}</a></p>
          <p style={{overflowWrap: 'anywhere'}}>Restricted agent: {wallet.vault.agent}</p>
          <p>Your existing wallet owns the vault. Only an administrator can increase its allowance or resume an on-chain pause.</p>
          {wallet.vault.chain && <>
            <p>{weiToEth(wallet.vault.chain.remaining)} ETH allowance · {weiToEth(wallet.vault.chain.balance)} ETH in escrow.</p>
            <p>{wallet.vault.chain.paused ? 'Paused on-chain' : wallet.vault.chain.expires * 1000 <= now ? 'Session expired' : 'Session active'} · expires {new Date(wallet.vault.chain.expires * 1000).toLocaleString()} · epoch {wallet.vault.epoch}.</p>
            <button className="btn btn-outline" disabled={busy || !roles.includes('proposer') || wallet.vault.chain.paused || BigInt(wallet.vault.chain.agent_balance) === 0n}
              onClick={() => void act(() => controlVault('PAUSE'), 'On-chain pause submitted. The receipt will confirm its result.')}>Pause vault</button>
            {!wallet.vault.chain.paused && <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}
              onClick={() => void act(() => controlVault('OWNER_PAUSE'), 'Administrator pause submitted from the owner wallet. It does not depend on the agent gas balance.')}>Pause vault as administrator</button>}
            {wallet.vault.chain.paused && <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}
              onClick={() => void act(() => controlVault('RESUME'), 'Administrator resume submitted. It does not extend the allowance or expiry.')}>Resume vault as administrator</button>}
          </>}
          {wallet.vault.chain && wallet.vault.chain.expires * 1000 <= now && <button className="btn btn-outline"
            disabled={busy || !roles.includes('policyAdmin')}
            onClick={() => void act(() => controlVault('CONFIGURE'), 'Administrator session grant submitted within the server limits. Earlier pending tasks retain their old grant and require review.')}>
            Renew session as administrator</button>}
          {wallet.vault.operations?.slice(0, 3).map(op => <p key={op.id}>{readableReason(op.kind)} · {readableReason(op.status)} {op.tx_hash && <a href={`https://sepolia.etherscan.io/tx/${op.tx_hash}`} target="_blank" rel="noopener noreferrer">View transaction</a>}</p>)}
        </> : <p>Deployment and the initial allowance require administrator setup.</p>}
      </div>}
      {wallet?.incoming_watch?.enabled && <p>Incoming token/NFT monitor: {wallet.incoming_watch.suspended_epoch != null ? 'paused for administrator review' : wallet.incoming_watch.block == null ? 'starting' : `confirmed block ${wallet.incoming_watch.block}`}. Incoming events cannot grant permission.</p>}
      {walletError && <p role="status">{walletError}</p>}
    </div>}
    {!roles.includes('proposer') && <p role="status">Connect the Proposer role using API key to start tasks and view progress. Existing human-approver and policy-administrator roles handle exceptions.</p>}
    <form className="autonomy-goal" onSubmit={event => {event.preventDefault(); void act(
      async () => {
        pendingGoal.current = goalSubmission(pendingGoal.current, goal);
        const result = await autonomyRequest('/goals', 'proposer', {goal, request_key: pendingGoal.current.key});
        pendingGoal.current = null;
        return result;
      }, 'Task started. Permitted steps will complete automatically.');}}>
      <label htmlFor="autonomous-goal">What should the wallet do?</label>
      <div><input id="autonomous-goal" value={goal} onChange={e => {editedGoal.current = true; setGoal(e.target.value);}} maxLength={500} required />
        <button className="btn btn-primary" disabled={busy || !roles.includes('proposer') || !!snapshot?.control.quarantined || (isSepolia && (!wallet?.payments_enabled || !!walletError || (wallet?.new_task_backend === 'VAULT' && !vaultReady(wallet.vault, now))))}>Start task</button></div>
    </form>
    <p role="status" aria-live="polite">{refreshError || notice}</p>
    <div className="autonomy-columns"><div><h3>Task timeline</h3>
      {!snapshot?.tasks.length && <p>{snapshot?.mandate ? 'No recorded tasks. Your standing mandate is ready; start a goal.' : snapshot ? 'No recorded tasks. Set a standing mandate, then give the wallet a goal.' : 'Task history is not loaded. Connect the Proposer role to view it.'}</p>}
      {snapshot?.tasks.map(task => <article className="autonomy-task" key={task.id}>
        <div className="autonomy-task-heading"><strong>Pay supplier · {weiToEth(String(task.amount))} ETH{task.payment_backend === 'VAULT' ? ' · guarded vault' : ''}</strong><span>{readableReason(task.state)}</span></div>
        <ol className="autonomy-steps">{['Balance', 'Funding', 'Payment', 'Verification'].map((name, index) =>
          <li key={name} data-state={autonomyStepState(task.state, task.steps[index]?.state)}>{name}<small>{readableReason(autonomyStepState(task.state, task.steps[index]?.state))}</small></li>)}</ol>
        {task.reason && <p>{readableReason(task.reason)}</p>}
        {isSepolia && task.state === 'HUMAN_REQUIRED' && <button className="btn btn-outline" disabled={busy || !roles.includes('proposer')}
          onClick={() => void act(() => autonomyRequest(`/goals/${task.id}/reconcile`, 'proposer', {}), 'Existing receipt checked without signing or broadcasting.')}>
          Reconcile existing payment</button>}
        {isMainWallet && task.state === 'HUMAN_REQUIRED' && ['RECONCILIATION_UNAVAILABLE', 'PREFLIGHT_UNAVAILABLE', 'PREFLIGHT_LIMIT_BLOCK'].includes(task.reason || '') && <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}
          onClick={() => void act(() => autonomyRequest(`/goals/${task.id}/resume-before-signing`, 'policyAdmin', {}), 'Administrator requested recovery of the same proposal. Signed outcomes cannot be retried here.')}>
          Retry before signing as administrator</button>}
        {transactionLinks(task).map(link => <p key={link.hash} style={{overflowWrap: 'anywhere'}}><a href={link.url} target="_blank" rel="noopener noreferrer">View Sepolia transaction · {link.hash}</a></p>)}
        <p className="autonomy-budget">Task payment ceiling {weiToEth(String(task.payment_cap))} ETH · funding ceiling {weiToEth(String(task.funding_cap))} ETH</p>
        {task.state === 'WAITING_APPROVAL' && <div className="autonomy-actions">
          {(['APPROVE', 'REJECT'] as const).map(decision => <button className="btn btn-outline" key={decision}
            disabled={busy || !roles.includes('approver')}
            onClick={() => void act(() => autonomyRequest(`/approvals/${task.id}/decision`, 'approver', {decision}), 'Human decision recorded.')}>
            {decision === 'APPROVE' ? 'Approve as human' : 'Reject as human'}</button>)}</div>}
        <details><summary>{task.events.length} persisted events</summary>
          {task.events.map(event => <p className="autonomy-event" key={event.id}>{readableReason(event.kind)}: {event.detail}</p>)}
        </details></article>)}
    </div><aside><h3>Exceptions inbox</h3>
      {!snapshot?.issues.some(issue => !issue.resolved) && <p>No open exceptions loaded.</p>}
      {snapshot?.issues.filter(issue => !issue.resolved).map(issue => <div className="autonomy-issue" key={issue.id}><strong>{readableReason(issue.reason)}</strong>
        <p>{issue.task_id ? `Task ${issue.task_id.slice(0, 8)}` : 'Untrusted event or instruction'}</p></div>)}
      {!!snapshot?.system_events?.length && <details><summary>Incoming events & system activity</summary>
        {snapshot.system_events.map(event => <p className="autonomy-event" key={event.id}>{readableReason(event.kind)}: {event.detail}</p>)}
      </details>}
      {!!snapshot?.control.quarantined && <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}
        onClick={() => void act(() => autonomyRequest('/quarantine/resume', 'policyAdmin', {}), 'Administrator resumed execution.')}>
        Resume as administrator</button>}
      <details className="autonomy-mandate"><summary>Standing mandate</summary>
        <form key={`${snapshot?.mandate?.version || 0}-${wallet?.approval_threshold_wei || ''}`} onSubmit={event => {event.preventDefault(); const form = new FormData(event.currentTarget);
          void act(() => autonomyRequest('/mandate', 'policyAdmin', {supplier: form.get('supplier'), recipient: form.get('recipient'),
            payment_cap: Number(form.get('payment')), funding_cap: form.get('funding'),
            approval_threshold: form.get('threshold')}, 'PUT'), 'Administrator mandate saved.');}}>
          <label>Supplier<input name="supplier" defaultValue={snapshot?.mandate?.supplier || wallet?.supplier || 'Acme'} required /></label>
          <label>Recipient<input name="recipient" defaultValue={snapshot?.mandate?.recipient || wallet?.recipient || (isSepolia ? '' : '0x' + '1'.repeat(40))} placeholder={isSepolia ? 'Administrator-configured recipient' : undefined} required /></label>
          <label>Session payment budget (wei)<input name="payment" type="number" min="1" max="1000000000000000" defaultValue={snapshot?.mandate?.payment_cap || '1000'} required /></label>
          <label>Funding budget (wei)<input name="funding" inputMode="numeric" pattern="[0-9]+" defaultValue={snapshot?.mandate?.funding_cap || (isSepolia ? '0' : '1000')} required /></label>
          <label>Human approval at (wei)<input name="threshold" inputMode="numeric" pattern="[0-9]+" defaultValue={wallet?.approval_threshold_wei || '50'} readOnly={wallet?.policy_managed} required /></label>
          <button className="btn btn-outline" disabled={busy || !roles.includes('policyAdmin')}>Save as administrator</button>
          <p>{isMainWallet ? 'This narrows workflow permissions within your existing policy and saved vendor limits. It does not replace the wallet policy.' : 'Replacing a mandate invalidates earlier pending tasks. The agent cannot raise limits.'}</p>
        </form></details>
    </aside></div>
  </section>;
}
