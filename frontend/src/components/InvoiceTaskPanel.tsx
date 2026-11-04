import type { InvoiceAgentTask } from '../invoiceAgent.ts';
import { invoiceAutomationDisabled, invoiceOutcome, taskStage } from '../invoiceAgent.ts';
import { safeAssistantExplorer } from '../assistant.ts';
import { invoiceReasonLabel } from '../invoices.ts';
export function InvoiceTaskPanel({ task, canCancel, onCancel, onInvoices }: {
  task: InvoiceAgentTask; canCancel: boolean; onCancel: () => void; onInvoices: () => void;
}) {
  return <section className="assistant-invoice-task" aria-live="polite">
    <div className="assistant-task-heading"><h3>{task.state === 'COMPLETED' ? 'Invoice status' : taskStage(task)}</h3><span>{task.mode === 'simulated' ? 'Simulation' : 'Sepolia'}</span></div>
    {task.items.map((item, index) => <article key={`${item.filename}:${index}`}>
      <div><h4>{item.filename}</h4><span className="assistant-invoice-outcome" data-state={item.state}>{invoiceOutcome(item.state)}</span></div>
      {item.vendor_name && <p>{item.vendor_name}{item.amount_eth && ` · ${item.amount_eth} ETH`}</p>}
      {item.reason && (['CHECKED', 'SIMULATED', 'VERIFIED'].includes(item.state)
        ? <details className="assistant-check-details"><summary>Check details</summary><p>{invoiceReasonLabel(item.reason)}</p></details>
        : <p>{invoiceReasonLabel(item.reason)}</p>)}
      {safeAssistantExplorer(item.explorer_url) && <a href={safeAssistantExplorer(item.explorer_url)!} target="_blank" rel="noopener noreferrer">View on Etherscan</a>}
    </article>)}
    {invoiceAutomationDisabled(task) && <p>Checks passed, but automatic execution is disabled on this backend.</p>}
    {task.cancel_requested && <p>Unsent work is stopping. Already signed or submitted transactions cannot be cancelled here.</p>}
    {task.reason && task.reason !== 'AUTOMATION_DISABLED' && <p>{task.reason.replaceAll('_', ' ').toLowerCase()}</p>}
    <div className="assistant-task-actions"><button className="btn btn-outline" onClick={onInvoices}>Open Accounts Payable</button>
      {task.can_cancel && <button className="btn btn-outline" disabled={!canCancel || task.cancel_requested} onClick={onCancel}>Stop unsent work</button>}</div>
  </section>;
}
