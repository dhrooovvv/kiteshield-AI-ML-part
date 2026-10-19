import { MandateDraftBox } from '../components/MandateDraftBox.tsx';
import { applyMandateDraft } from '../mandateDraft.ts';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { api } from '../api/client.ts';
import { ethToWei, weiToEth } from '../amounts.ts';
import { useRole, useConnectedRoles } from '../useCredentials.ts';
import type { TreasuryStatus, TreasuryAction, TreasuryConfig } from '../treasury.ts';
import { treasuryExecuteBlockers } from '../treasury.ts';
import type { Proposal } from '../types/index.ts';
import { ProposalCard } from '../components/ProposalCard.tsx';

const modeLabel = { off: 'Off', plan_only: 'Plan-only', execute: 'Execute' };
const amount = (wei?: string) => wei === undefined ? 'Unavailable' : `${weiToEth(wei)} ETH`;

export function TreasurySummary({ status, children, latestAction, activity }: { status: TreasuryStatus; children?: ReactNode; latestAction?: TreasuryAction; activity?: ReactNode }) {
  const m = status.mandate, o = status.observation;
  const active = status.mode === 'execute' && status.execution.available;
  const eligible = status.mode !== 'off' && status.observation_fresh && status.plan?.state === 'ELIGIBLE';
  return <div className="treasury-dashboard-grid">
    <section className="treasury-configuration" aria-labelledby="treasury-heading">
    <header><h2 id="treasury-heading">Mandate configuration</h2><span>{m ? `Version ${m.version}` : 'Not configured'}</span></header>
    <dl className="treasury-facts treasury-config-facts">
      <div><dt>Sender wallet</dt><dd><details><summary>{status.sender.slice(0, 10)}…{status.sender.slice(-6)}</summary>{status.sender}</details></dd></div>
      <div><dt>Sweep recipient</dt><dd>{m ? <details><summary>{m.recipient.slice(0, 10)}…{m.recipient.slice(-6)}</summary>{m.recipient}</details> : 'Not configured'}</dd></div>
      <div><dt>Target balance</dt><dd>{amount(m?.target_balance_wei)}</dd></div>
      <div><dt>Maximum sweep</dt><dd>{amount(m?.sweep_maximum_wei)}</dd></div>
      <div><dt>Minimum excess</dt><dd>{amount(m?.minimum_excess_wei)}</dd></div>
      <div><dt>Cooldown interval</dt><dd>{m ? `${m.cooldown_seconds}s` : 'Not configured'}</dd></div>
    </dl>
    {children}
    </section>
    <section className="treasury-eligibility" aria-labelledby="treasury-eligibility-heading">
      <header><h2 id="treasury-eligibility-heading">Sweep eligibility</h2><strong>{modeLabel[status.mode]}</strong></header>
      <p className="treasury-monitor-state">{active ? 'Execution enabled · monitoring active' : status.mode === 'execute' ? 'Execution paused' : status.mode === 'plan_only' ? 'Plan-only preview · execution not enabled' : 'Autopilot is off'}</p>
      <div className="treasury-candidate"><span>{eligible ? 'Eligible sweep · not executed' : 'Proposed amount · not executed'}</span><strong>{amount(status.observation_fresh ? status.plan?.proposed_amount_wei : undefined)}</strong><p>{status.mode === 'off' ? 'Disabled' : !status.observation_fresh ? 'Observe again · snapshot stale or unavailable' : status.plan?.reason.replaceAll('_', ' ').toLowerCase() ?? 'Observe in plan-only mode first'}</p></div>
      <dl className="treasury-live-facts">
        <div><dt>Observed balance</dt><dd>{amount(o?.balance_wei)}</dd></div>
        <div><dt>Maximum fee reserve</dt><dd>{amount(o?.maximum_fee_reserve_wei)}</dd></div>
        <div><dt>Daily action usage · UTC</dt><dd>{status.daily_actions_used} / {m?.daily_action_limit ?? '—'}</dd></div>
        <div><dt>Cooldown</dt><dd>{status.cooldown_active ? 'Active' : 'Not active'}</dd></div>
      </dl>
      <details className="treasury-observation"><summary>Observation details · {status.observation_fresh ? 'Fresh' : 'Stale / unavailable'}</summary><p>{o ? new Date(o.observed_at).toLocaleString() : 'Not observed'} · Block {o?.block_number ?? 'Unavailable'}</p></details>
      <p>{status.execution.available ? 'Execution available within policy and mandate limits.' : `Execution unavailable: ${status.execution.reason?.replaceAll('_', ' ').toLowerCase() ?? 'not verified'}.`}</p>
      {latestAction && <p className="treasury-latest-execution">Latest execution: {latestAction.simulation ? 'Simulated · not broadcast' : latestAction.execution_status?.replaceAll('_', ' ').toLowerCase() ?? 'not started'}{!latestAction.simulation && latestAction.explorer_url && <> · <a href={latestAction.explorer_url} target="_blank" rel="noreferrer">View transaction</a></>}</p>}
      {active && <p>Monitoring can initiate an eligible sweep. Only a matching receipt confirms payment.</p>}
    {status.plan?.state === 'BELOW_TARGET' && <p role="alert" className="treasury-alert">Balance below target. Human refill required; Autopilot cannot refill this wallet.</p>}
    {o?.status === 'unavailable' && <p role="alert">Observation unavailable: {o.reason}. No balance or payment is inferred.</p>}
    {o?.fee_error && <p role="alert">Fee estimate unavailable. Execution is blocked.</p>}
    {o?.simulation && <p>Simulation fee estimate · no on-chain execution.</p>}
    </section>
    {activity}
  </div>;
}

interface Props { refreshRevision: number; onOpenAudit: (cid: string) => void; onOpenDetails: (p: Proposal) => void }

export function TreasuryActivity({ actions, onOpenAudit, onOpenHistory, showAll = false }: { actions: TreasuryAction[]; onOpenAudit: (cid: string) => void; onOpenHistory?: () => void; showAll?: boolean }) {
  const renderAction = (action: TreasuryAction) => <div className="treasury-action" key={action.id}><div><strong>{action.state.replaceAll('_', ' ')}</strong><p>Mandate v{action.mandate_version} · {new Date(action.created_at).toLocaleString()} · Block {action.observation.block_number ?? 'unavailable'}</p><p>{action.reason.replaceAll('_', ' ').toLowerCase()}{action.simulation ? ' · Simulated, not broadcast' : ''}</p></div><button className="btn btn-outline" onClick={() => onOpenAudit(action.id)}>View audit</button></div>;
  return <>{!actions.length && <p>No observations or actions recorded.</p>}{(showAll ? actions : actions.slice(0, 1)).map(renderAction)}{!showAll && actions.length > 1 && <button className="btn btn-outline" onClick={onOpenHistory}>Earlier activities ({actions.length - 1})</button>}</>;
}

function TreasuryHistoryDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const opener = document.activeElement;
    dialog.current?.showModal();
    return () => { if (opener instanceof HTMLElement && opener.isConnected) opener.focus(); };
  }, []);
  if (typeof document === 'undefined') return null;
  return createPortal(<dialog ref={dialog} className="treasury-history-dialog" aria-labelledby="treasury-history-title" onCancel={onClose}>
    <header><h2 id="treasury-history-title">{title}</h2><button className="btn btn-outline" onClick={onClose}>Close</button></header>
    <div className="treasury-history-body treasury-page">{children}</div>
  </dialog>, document.body);
}

export function TreasuryView({ refreshRevision, onOpenAudit, onOpenDetails }: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  const admin = useRole('policyAdmin');
  const roles = useConnectedRoles();
  const [status, setStatus] = useState<TreasuryStatus | null>(null);
  const [actions, setActions] = useState<TreasuryAction[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [history, setHistory] = useState<'activities' | 'payments' | null>(null);
  const refresh = useCallback(async () => {
    try {
      const [next, recent] = await Promise.all([api.getTreasury(), api.getTreasuryActions()]);
      const linked = [...new Set(recent.flatMap(a => a.proposal_id ? [a.proposal_id] : []))];
      const records = await Promise.all(linked.map(id => api.getProposal(id)));
      setStatus(next); setActions(recent); setProposals(records); setError(null);
    } catch (err) { setStatus(null); setError(err instanceof Error ? err.message : 'Treasury unavailable'); }
  }, []);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void refresh(); });
    // Saved status only: these GETs never trigger RPC observation or execution.
    const timer = setInterval(() => { if (active) void refresh(); }, 15000);
    return () => { active = false; clearInterval(timer); };
  }, [refresh, refreshRevision, roles]);
  const executeBlockers = status ? treasuryExecuteBlockers(status, admin) : [];
  const perform = async (task: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await task(); setConfirm(null); setEditing(null); await refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'Operation failed'); }
    finally { setBusy(false); }
  };
  const save = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (key: string) => String(form.get(key) ?? '');
    void perform(async () => {
      const config: TreasuryConfig = { sender: status!.sender, recipient: text('recipient'), chain_id: 11155111,
        target_balance_wei: text('target') === '0' ? '0' : ethToWei(text('target')),
        sweep_maximum_wei: ethToWei(text('maximum')), minimum_excess_wei: ethToWei(text('minimum')),
        cooldown_seconds: Number(text('cooldown')), daily_action_limit: Number(text('daily')),
        freshness_seconds: Number(text('freshness')) };
      await api.saveTreasury(config, editing!);
    });
  };
  return <div className="treasury-page">
    {error && <p role="alert" className="state-panel state-error">{error}</p>}
    {!status ? <button className="btn btn-outline" onClick={() => void refresh()}>Reload treasury status</button> : <>
      <TreasurySummary status={status} latestAction={actions.find(action => action.proposal_id !== null)} activity={
        <section className="treasury-actions" aria-labelledby="treasury-activity-heading">
          <h2 id="treasury-activity-heading">Autopilot activity</h2>
          <TreasuryActivity actions={actions} onOpenAudit={onOpenAudit} onOpenHistory={() => setHistory('activities')} />
          {proposals.length > 0 && <button className="btn btn-outline treasury-payment-history" onClick={() => setHistory('payments')}>Payment details ({proposals.length})</button>}
        </section>
      }>
      <section className="treasury-controls" aria-label="Mandate controls">
        {!admin && <p>Policy administrator required to configure, observe or activate a mandate.</p>}
        <div className="treasury-buttons">
          <button className="btn btn-outline" onClick={() => void refresh()} disabled={busy}>Refresh status (read-only)</button>
          <button className="btn btn-outline" disabled={!admin || busy} onClick={() => setEditing(editing === null ? status.mandate?.version ?? 0 : null)}>Configure mandate</button>
          <button className="btn btn-outline" disabled={!admin || busy || !status.mandate} onClick={() => void perform(() => api.setTreasuryMode('plan_only', status.mandate!.version))}>Enable plan-only</button>
          <button className="btn btn-outline" disabled={!admin || busy || status.mode === 'off'} onClick={() => void perform(() => api.observeTreasury())}>Observe once · plan-only</button>
          <button className="btn btn-emerald" aria-describedby="treasury-execute-requirements" disabled={busy || executeBlockers.length > 0} onClick={() => setConfirm(status.mandate!.version)}>Enable execute…</button>
          <button className="btn btn-outline" disabled={!admin || busy || status.mode === 'off'} onClick={() => void perform(() => api.setTreasuryMode('off', status.mandate!.version))}>Disable</button>
        </div>
        <div id="treasury-execute-requirements" aria-live="polite">
          {executeBlockers.length > 0 && status.mode !== 'execute' && <><p>Before enabling execute:</p><ul>{executeBlockers.map(reason => <li key={reason}>{reason}</li>)}</ul></>}
        </div>
        {confirm !== null && <div className="treasury-confirm" role="group" aria-label="Confirm standing spending permission"><h3>Grant standing execution permission?</h3><p>This allows unattended sweeps to the designated recipient within this mandate and current policy. Disabling prevents fresh signing but cannot cancel a signed or broadcast transaction.</p>{confirm !== status.mandate?.version && <p role="alert">The mandate changed. Cancel and review its new configuration before confirming.</p>}<button className="btn btn-emerald" disabled={busy || !admin || confirm !== status.mandate?.version || executeBlockers.length > 0} onClick={() => void perform(() => api.setTreasuryMode('execute', confirm, true))}>Confirm standing permission</button><button className="btn btn-outline" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button></div>}
        {editing !== null && <form ref={formRef} onSubmit={save} className="treasury-form"><h3>Mandate settings</h3><p>Saving disables this mandate and invalidates old unsigned proposals. Cooldown and action history are retained.</p>{editing !== (status.mandate?.version ?? 0) && <p role="alert">The mandate changed. Close configuration and reopen it before saving.</p>}
          <MandateDraftBox disabled={!admin || busy || editing !== (status.mandate?.version ?? 0)} onApply={draft => {
            if (formRef.current) applyMandateDraft(formRef.current, draft);
          }} />
          <label>Sweep recipient<input name="recipient" required defaultValue={status.mandate?.recipient} /></label>
          <label>Target balance (ETH)<input name="target" inputMode="decimal" required defaultValue={status.mandate ? weiToEth(status.mandate.target_balance_wei) : ''} /></label>
          <label>Maximum sweep (ETH)<input name="maximum" inputMode="decimal" required defaultValue={status.mandate ? weiToEth(status.mandate.sweep_maximum_wei) : '0.00003'} /></label>
          <label>Minimum excess after fees (ETH)<input name="minimum" inputMode="decimal" required defaultValue={status.mandate ? weiToEth(status.mandate.minimum_excess_wei) : '0.00002'} /></label>
          <label>Cooldown (seconds)<input name="cooldown" type="number" min="60" max="86400" required defaultValue={status.mandate?.cooldown_seconds ?? 600} /></label>
          <label>Maximum actions per UTC day<input name="daily" type="number" min="1" max="100" required defaultValue={status.mandate?.daily_action_limit ?? 3} /></label>
          <label>Observation freshness (seconds)<input name="freshness" type="number" min="15" max="300" required defaultValue={status.mandate?.freshness_seconds ?? 60} /></label>
          <button className="btn btn-emerald" disabled={busy || !admin || editing !== (status.mandate?.version ?? 0)}>Save disabled mandate</button>
        </form>}
        {busy && <p role="status">Updating treasury…</p>}
      </section>
      </TreasurySummary>
      {history !== null && <TreasuryHistoryDialog title={history === 'activities' ? 'Earlier Autopilot activities' : 'Payment details'} onClose={() => setHistory(null)}>
        {history === 'activities' ? <TreasuryActivity actions={actions.slice(1)} showAll onOpenAudit={cid => { setHistory(null); onOpenAudit(cid); }} />
          : proposals.map(p => <ProposalCard key={p.id} proposal={p} onUpdated={() => void refresh()} onOpenAudit={cid => { setHistory(null); onOpenAudit(cid); }} onOpenDetails={proposal => { setHistory(null); onOpenDetails(proposal); }} executionMode={status.execution.execution_mode} />)}
      </TreasuryHistoryDialog>}
    </>}
  </div>;
}
