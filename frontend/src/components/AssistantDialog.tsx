import { autonomyRequest, readableReason, type AutonomyTask } from '../autonomy.ts';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpRight, MessageSquare, Send } from 'lucide-react';
import { api } from '../api/client.ts';
import { useConnectedRoles, useRole } from '../useCredentials.ts';
import { assistantExamples, assistantFactLabels, safeAssistantExplorer, contextualQuestion } from '../assistant.ts';
import type { AssistantAnswer } from '../assistant.ts';
import type { Proposal, BackendHealth } from '../types/index.ts';
import { refreshPaymentReceipts } from '../paymentReceipts.ts';
import { VoiceControl } from './VoiceControl.tsx';
import { InvoiceTaskPanel } from './InvoiceTaskPanel.tsx';
import type { InvoiceAgentTask } from '../invoiceAgent.ts';
import { invoiceOutcome, taskFinished } from '../invoiceAgent.ts';

export function AssistantResult({ answer, onFund, onDetails }: {
  answer: AssistantAnswer; onFund?: () => void; onDetails?: (id: string) => void;
}) {
  const data = answer.data ?? {};
  return <section className="assistant-result">
    <h3>{answer.title}</h3>
    {answer.message && <p>{answer.message}</p>}
    {data.status === 'unavailable' && <p role="alert">{data.message ?? 'Current data unavailable.'}</p>}
    {data.holdings && <><p className="assistant-source">Live Sepolia RPC · as of block {String(data.block_number ?? 'unavailable')}</p>
      {data.holdings.map(row => <div className="assistant-holding" key={`${row.asset}:${row.address}`}>
        <div><strong>{row.asset}</strong><span>{row.role} · {row.address.slice(0, 8)}…{row.address.slice(-6)}</span></div>
        <strong>{row.balance}</strong></div>)}</>}
    <dl className="assistant-facts">{Object.entries(data).filter(([key, value]) => assistantFactLabels[key] &&
      (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')).map(([key, value]) =>
      <div key={key}><dt>{assistantFactLabels[key]}</dt><dd>{typeof value === 'boolean' ? value ? 'Yes' : 'No' : String(value)}</dd></div>)}</dl>
    {data.states && <dl className="assistant-facts">{Object.entries(data.states).map(([key, count]) =>
      <div key={key}><dt>{key.replaceAll('_', ' ').toLowerCase()}</dt><dd>{count}</dd></div>)}</dl>}
    {data.payments && <div className="assistant-payments">{!data.payments.length ? <p>No matching confirmed payments in KiteShield.</p> : data.payments.map(item => {
      const explorer = safeAssistantExplorer(item.explorer_url);
      return <article key={item.proposal_id}><div><strong>{item.amount_eth} ETH</strong><time>{new Date(item.recorded_at).toLocaleString()}</time></div>
        <p className="assistant-address">{item.recipient}</p><div><span>{item.status.toLowerCase()}</span>
          {explorer && <a href={explorer} target="_blank" rel="noopener noreferrer">Etherscan <ArrowUpRight size={13} /></a>}
          {onDetails && <button className="btn btn-outline" onClick={() => onDetails(item.proposal_id)}>Details</button>}</div></article>;
    })}</div>}
    {data.items?.map(item => <p key={item.proposal_id}>#{item.proposal_id.slice(0, 8)} · expires {new Date(item.expires_at).toLocaleString()}</p>)}
    {data.basis && <p className="assistant-source">{data.basis}</p>}
    {answer.kind === 'funding' && onFund && <button className="btn btn-outline" onClick={onFund}>Open test ETH funding</button>}
  </section>;
}

export function AssistantDialog({ onClose, onFund, onProposal, onDetails, health, onInvoices, onTaskComplete }: {
  onClose: () => void; onFund: () => void; onProposal: (proposal: Proposal) => void;
  onDetails: (proposal: Proposal) => void; health: BackendHealth | null;
  onInvoices?: () => void; onTaskComplete?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const roles = useConnectedRoles();
  const canPay = useRole('proposer');
  const [prompt, setPrompt] = useState('');
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState<Proposal | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [invoiceTask, setInvoiceTask] = useState<InvoiceAgentTask | null>(null);
  const lastRead = useRef<{ question: string; kind: string } | undefined>(undefined);
  const finishedTask = useRef('');
  const [voiceReply, setVoiceReply] = useState<AssistantAnswer | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const autonomousTaskId = answer?.kind === 'autonomous_task' ? answer.data?.task_id : undefined;
  useEffect(() => {
    if (!autonomousTaskId) return;
    let cancelled = false;
    const deadline = Date.now() + 300000;
    const timer = setInterval(() => {
      void autonomyRequest<AutonomyTask>('/goals/' + autonomousTaskId).then(task => {
        if (cancelled) return;
        setAnswer(current => current?.data?.task_id === autonomousTaskId ? {...current,
          title: 'Autonomous task: ' + readableReason(task.state),
          data: {...current.data, state: task.state}} : current);
        if (['COMPLETED', 'REJECTED', 'HUMAN_REQUIRED'].includes(task.state) || Date.now() > deadline) clearInterval(timer);
      }).catch(() => { if (!cancelled) setError('Task progress unavailable. Check Autonomous Tasks; do not repeat the payment.'); clearInterval(timer); });
    }, 1500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [autonomousTaskId]);
  const taskId = invoiceTask?.task_id;
  const taskState = invoiceTask?.state;
  const taskAwaitingReceipt = invoiceTask?.items.some(item => ['PAID', 'UNCERTAIN'].includes(item.state));
  const taskAwaitingExecution = health?.auto_execute_enabled && health.execution_mode === 'sepolia' &&
    invoiceTask?.items.some(item => item.state === 'CHECKED');
  const taskReceiptDeadline = useRef({ id: '', at: 0 });
  useEffect(() => {
    if (!roles.length) return;
    let cancelled = false;
    void api.getInvoiceTasks().then(tasks => {
      if (!cancelled && tasks.length) setInvoiceTask(current => current ?? tasks[0]);
    }).catch(() => { /* Questions remain available if invoice commands are unavailable. */ });
    return () => { cancelled = true; };
  }, [roles]);
  useEffect(() => {
    if (!taskId || (['COMPLETED', 'NEEDS_ATTENTION', 'CANCELLED', 'FAILED'].includes(taskState ?? '') && !taskAwaitingReceipt && !taskAwaitingExecution)) return;
    if (taskReceiptDeadline.current.id !== taskId) taskReceiptDeadline.current = { id: taskId, at: Date.now() + 120000 };
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const next = await api.getInvoiceTask(taskId);
        if (cancelled) return;
        setInvoiceTask(next);
        const awaitingExecution = health?.auto_execute_enabled && health.execution_mode === 'sepolia' &&
          next.items.some(item => item.state === 'CHECKED');
        if (!taskFinished(next) || ((awaitingExecution || next.items.some(item => ['PAID', 'UNCERTAIN'].includes(item.state))) && Date.now() < taskReceiptDeadline.current.at)) timer = setTimeout(check, 2000);
      } catch { if (!cancelled) setError('Task status unavailable. Reopen the assistant to recover the same task.'); }
    };
    timer = setTimeout(check, 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [taskId, taskState, taskAwaitingReceipt, taskAwaitingExecution, health?.auto_execute_enabled, health?.execution_mode]);
  useEffect(() => {
    if (invoiceTask && taskFinished(invoiceTask) && finishedTask.current !== invoiceTask.task_id) {
      finishedTask.current = invoiceTask.task_id;
      queueMicrotask(() => setVoiceReply({ kind: 'invoice_result', title: 'Invoice status', message: invoiceTask.items.map(item => `${item.filename}: ${invoiceOutcome(item.state)}`).join('. ') }));
      onTaskComplete?.();
    }
  }, [invoiceTask, onTaskComplete]);
  const submittedId = submitted?.id;
  const submittedTransactionState = submitted?.transaction?.status;
  const receiptDeadline = useRef({ id: '', at: 0 });
  useEffect(() => {
    if (!submittedId || !submitted || submitted.transaction?.execution_mode !== 'sepolia' ||
      !['SIGNED', 'SUBMITTED'].includes(submittedTransactionState ?? '')) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    if (receiptDeadline.current.id !== submittedId) receiptDeadline.current = { id: submittedId, at: Date.now() + 120000 };
    const deadline = receiptDeadline.current.at;
    const check = async () => {
      const result = await refreshPaymentReceipts([submitted], id => api.getTransaction(id));
      if (cancelled) return;
      const updated = result.proposals[0];
      setSubmitted(updated);
      if (result.failed) setError('Receipt unavailable. View the existing proposal to check again.');
      else if (['SIGNED', 'SUBMITTED'].includes(updated.transaction?.status ?? '') && Date.now() < deadline) timer = setTimeout(check, 3000);
    };
    timer = setTimeout(check, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
    // The persisted submission is polled only while its lifecycle state is pending.
  }, [submitted, submittedId, submittedTransactionState]);
  useEffect(() => {
    active.current = true;
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden'; dialog.current?.showModal();
    return () => { active.current = false; document.body.style.overflow = overflow; opener?.focus(); };
  }, []);
  const run = async (action: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try { await action(); } catch (e) { if (active.current) setError(e instanceof Error ? e.message : 'Request failed.'); }
    finally { inFlight.current = false; if (active.current) setBusy(false); }
  };
  const askText = (text: string, selectedFileId?: string) => {
    if (!text.trim() || !roles.length) return;
    const question = contextualQuestion(text, lastRead.current);
    setPrompt(text);
    void run(async () => {
      const response = await api.askAssistant(question, selectedFileId);
      if (!active.current) return;
      setAnswer(response); setVoiceReply(response); setSubmitted(response.data?.submitted_proposal ?? null); setUncertain(false);
      if (response.data?.submitted_proposal) onProposal(response.data.submitted_proposal);
      if (response.kind === 'invoice_task' && response.data) setInvoiceTask(response.data as unknown as InvoiceAgentTask);
      if (response.kind === 'payments') lastRead.current = { question, kind: response.kind };
      else lastRead.current = undefined;
    });
  };
  const draft = answer?.kind === 'payment' ? answer.data : undefined;
  const submittedExplorer = submitted?.chain_id === 11155111 &&
    submitted.transaction?.execution_mode === 'sepolia' &&
    ['SUBMITTED', 'CONFIRMED', 'REVERTED', 'UNCERTAIN'].includes(submitted.transaction.execution_outcome ?? '')
    ? safeAssistantExplorer(`https://sepolia.etherscan.io/tx/${submitted.transaction.tx_hash}`) : null;
  return createPortal(<dialog ref={dialog} className="assistant-dialog" aria-labelledby="assistant-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <header><div><h2 id="assistant-title"><MessageSquare size={21} /> Ask KiteShield</h2>
      <p>Ask about your wallet or process an invoice.</p></div>
      <div className="assistant-header-actions"><span className="assistant-environment">{health?.execution_mode === 'simulated' ? 'Simulation · no live payment' : health?.verified_chain_id === 11155111 ? 'Sepolia · test ETH' : 'Execution mode unverified'}</span>
        <button className="btn btn-outline" disabled={busy} onClick={onClose}>Close</button></div></header>
    <div className="assistant-body">
      <section className="assistant-command-pane" aria-label="Ask a question or give a command">
      {!roles.length && <p>Connect an API role to ask questions. Payments require Proposer.</p>}
      <form onSubmit={event => { event.preventDefault(); if (!prompt.trim() || !roles.length) return;
        askText(prompt); }}>
        <label htmlFor="assistant-prompt">What would you like to do?</label>
        <textarea id="assistant-prompt" rows={3} maxLength={2000} required value={prompt} disabled={busy}
          onChange={event => { setPrompt(event.target.value); setAnswer(null); setSubmitted(null); }}
          placeholder="How much did I pay last month? Or: Send 0.00001 ETH to 0x…" />
        {health?.auto_execute_enabled && health.execution_mode === 'sepolia' && <p className="assistant-auto-note">Eligible payments execute when you press Ask{health.local_voice_enabled ? '' : ' or release voice input'}. Current policy, saved-vendor and automation limits apply.</p>}
        <div className="assistant-composer-footer"><VoiceControl disabled={busy || !roles.length} onText={setPrompt} onCommand={askText} reply={voiceReply} /><button className="btn btn-primary" disabled={busy || !roles.length || !prompt.trim()}><Send size={15} />{busy ? 'Working…' : 'Ask'}</button></div>
      </form>
      {error && <p className="assistant-error" role="alert">{error}</p>}
      <section className="assistant-suggestions" aria-labelledby="assistant-suggestions-title"><h3 id="assistant-suggestions-title">Try a command</h3>
        <div className="assistant-examples">{assistantExamples.map(example => <button className="btn btn-outline" disabled={busy} key={example}
          onClick={() => { setPrompt(example); setAnswer(null); setSubmitted(null); }}>{example}</button>)}</div>
      </section>
      </section>
      <section className="assistant-output-pane" aria-label="Results and invoice activity">
      {!answer && !invoiceTask && <div className="assistant-empty-result"><h3>Results & activity</h3><p>Ask a question or choose a command to get started.</p><p>Invoice progress and payment details will appear here.</p></div>}
      {answer && answer.kind !== 'invoice_task' && <AssistantResult answer={answer} onFund={onFund} onDetails={id => void run(async () => onDetails(await api.getProposal(id)))} />}
      {answer?.kind === 'invoice_choices' && <div className="assistant-file-choices">{answer.data?.choices?.map(choice => <button key={choice.id} className="btn btn-outline" disabled={busy || !canPay} onClick={() => askText(prompt, choice.id)}>{choice.name} · {choice.folder}</button>)}</div>}
      {invoiceTask && (!answer || ['invoice_task', 'invoice_choices'].includes(answer.kind)) && <InvoiceTaskPanel task={invoiceTask} canCancel={canPay && !busy}
        onInvoices={() => onInvoices?.()} onCancel={() => void run(async () => setInvoiceTask(await api.cancelInvoiceTask(invoiceTask.task_id)))} />}
      {answer?.kind === 'invoice_task' && answer.message && <p role="status">{answer.message}</p>}
      {draft && <div className="assistant-payment-review">
        <div><strong>{draft.amount_eth} ETH</strong><span>{draft.mode === 'simulated' ? 'Simulation' : 'Sepolia · chain 11155111'}</span></div>
        <p className="assistant-address">To {draft.recipient}</p>
        {typeof draft.vendor_name === 'string' && <p>Approved vendor: {draft.vendor_name}</p>}
        {!canPay && <p>Connect Proposer to submit. Approver and policy administrator cannot submit payments.</p>}
        {submitted ? <><p role="status">Proposal #{submitted.id.slice(0, 8)} · {submitted.transaction?.execution_outcome ?? submitted.status}. View its current state in Proposals.</p>
          {submittedExplorer && <p><a href={submittedExplorer} target="_blank" rel="noopener noreferrer">View on Etherscan</a></p>}
          <button className="btn btn-outline" onClick={() => void run(async () => onDetails(await api.getProposal(submitted.id)))}>View proposal</button></>
          : <button className="btn btn-primary" disabled={!canPay || busy || !draft.draft_id} onClick={() => void run(async () => {
            setUncertain(true);
            const proposal = await api.submitAssistantPayment(draft.draft_id!);
            if (active.current) { setSubmitted(proposal); setUncertain(false); onProposal(proposal); }
          })}>{busy ? 'Submitting…' : uncertain ? 'Recover same proposal' : 'Submit payment request'}</button>}
        {uncertain && !busy && <p>The response was interrupted or rejected. Recovery reuses this draft and its existing proposal; it never creates another payment.</p>}
      </div>}
      </section>
    </div>
  </dialog>, document.body);
}
