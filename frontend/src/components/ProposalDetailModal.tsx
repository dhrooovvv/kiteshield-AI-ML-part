import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { DecisionBadge } from './DecisionBadge.tsx';
import { StatusBadge } from './StatusBadge.tsx';
import { FeeCheck } from './FeeCheck.tsx';
import { humanizeEvent } from '../auditPresentation.ts';
import type { Proposal } from '../types/index.ts';

interface ProposalDetailModalProps {
  proposal: Proposal;
  onClose: () => void;
  onOpenAudit: (correlationId: string) => void;
}

const tabs = [
  { id: 'summary', label: 'Summary' },
  { id: 'fees', label: 'Fee estimate' },
  { id: 'policy', label: 'Policy & history' },
] as const;
type DetailTab = typeof tabs[number]['id'];

export const ProposalDetailModal: React.FC<ProposalDetailModalProps> = ({
  proposal, onClose, onOpenAudit,
}) => {
  const [activeTab, setActiveTab] = useState<DetailTab>('summary');
  const dialogRef = useRef<HTMLDialogElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();

  useEffect(() => {
    const previousFocus = document.activeElement;
    dialogRef.current?.showModal();
    return () => { if (previousFocus instanceof HTMLElement) previousFocus.focus(); };
  }, []);

  return createPortal(
    <dialog ref={dialogRef} className="proposal-dialog" aria-labelledby={id + '-title'} onCancel={onClose}>
      <header className="proposal-dialog-header">
        <div>
          <h2 id={id + '-title'}>Proposal details</h2>
          <p>#{proposal.id.slice(0, 8)} · {new Date(proposal.created_at).toLocaleString()}</p>
        </div>
        <button className="btn btn-outline" onClick={onClose}>Close</button>
      </header>
      <div className="proposal-dialog-status">
        <div><span>Status</span><StatusBadge status={proposal.status} /></div>
        <div><span>Policy decision</span><DecisionBadge decision={proposal.policy_decision?.decision} /></div>
      </div>
      <div className="proposal-dialog-tabs" role="tablist" aria-label="Proposal details">
        {tabs.map((tab, index) => <button key={tab.id} ref={(element) => { tabRefs.current[index] = element; }}
          type="button" role="tab" id={id + '-tab-' + tab.id} aria-controls={id + '-panel-' + tab.id}
          aria-selected={activeTab === tab.id} tabIndex={activeTab === tab.id ? 0 : -1}
          onClick={() => setActiveTab(tab.id)}
          onKeyDown={(event) => {
            let nextIndex = index;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
            else if (event.key === 'ArrowLeft') nextIndex = (index + tabs.length - 1) % tabs.length;
            else if (event.key === 'Home') nextIndex = 0;
            else if (event.key === 'End') nextIndex = tabs.length - 1;
            else return;
            event.preventDefault();
            setActiveTab(tabs[nextIndex].id);
            tabRefs.current[nextIndex]?.focus();
          }}>{tab.label}</button>)}
      </div>
      <div className="proposal-dialog-content">
        <section role="tabpanel" id={id + '-panel-summary'} aria-labelledby={id + '-tab-summary'} hidden={activeTab !== 'summary'} tabIndex={0}>
          <dl className="proposal-summary">
            <div><dt>Transfer amount</dt><dd className="proposal-summary-amount">{proposal.amount_eth} ETH</dd></div>
            <div><dt>Network</dt><dd>{proposal.chain_id === 11155111 ? 'Sepolia' : 'Chain ' + proposal.chain_id} <span className="proposal-muted">({proposal.chain_id})</span></dd></div>
            <div className="proposal-summary-wide"><dt>Recipient</dt><dd>{proposal.recipient}</dd></div>
            <div><dt>Exact amount (wei)</dt><dd>{proposal.amount_wei}</dd></div>
            <div><dt>Asset</dt><dd>{proposal.asset_type === 'NATIVE_ETH' ? 'Native ETH' : proposal.asset_type}</dd></div>
          </dl>
          <div className="proposal-source"><h3>Original request</h3><p>{proposal.prompt || 'No original request recorded.'}</p></div>
        </section>
        <section role="tabpanel" id={id + '-panel-fees'} aria-labelledby={id + '-tab-fees'} hidden={activeTab !== 'fees'} tabIndex={0}>
          <FeeCheck key={proposal.id + ':' + proposal.amount_wei} valueWei={proposal.amount_wei} />
        </section>
        <section role="tabpanel" id={id + '-panel-policy'} aria-labelledby={id + '-tab-policy'} hidden={activeTab !== 'policy'} tabIndex={0}>
          {proposal.policy_decision ? <div className="proposal-policy">
            <h3>Policy version {proposal.policy_decision.policy_version}</h3>
            <ul>{proposal.policy_decision.reason_codes.map((code, index) => <li key={index}>{humanizeEvent(code)}</li>)}</ul>
            <p className="proposal-muted">Evaluated {new Date(proposal.policy_decision.evaluated_at).toLocaleString()}</p>
          </div> : <p>This proposal has not been evaluated against a policy.</p>}
          {proposal.approval && <div className="proposal-source">
            <h3>Human approval</h3><dl className="audit-facts"><dt>Status</dt><dd>{humanizeEvent(proposal.approval.status)}</dd><dt>Expires</dt><dd>{new Date(proposal.approval.expires_at).toLocaleString()}</dd></dl>
          </div>}
          {proposal.transaction && <div className="proposal-source">
            <h3>Transaction</h3><dl className="audit-facts"><dt>Status</dt><dd>{humanizeEvent(proposal.transaction.status)}</dd><dt>Transaction hash</dt><dd>{proposal.transaction.tx_hash || 'Not broadcast'}</dd></dl>
          </div>}
          <details className="proposal-source"><summary>Technical references</summary><dl className="audit-facts"><dt>Proposal ID</dt><dd>{proposal.id}</dd><dt>Request reference</dt><dd>{proposal.correlation_id}</dd></dl></details>
        </section>
      </div>
      <footer className="proposal-dialog-footer">
        <button className="btn btn-outline" onClick={() => { onClose(); onOpenAudit(proposal.correlation_id); }}>View audit trail</button>
      </footer>
    </dialog>, document.body
  );
};
