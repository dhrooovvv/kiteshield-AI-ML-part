import React, { useState } from 'react';
import {
  ExternalLink,
  ShieldCheck,
  History,
  Lock,
  Clock,
  FileText,
} from 'lucide-react';
import { DecisionBadge } from './DecisionBadge.tsx';
import { StatusBadge } from './StatusBadge.tsx';
import { humanizeEvent } from '../auditPresentation.ts';
import { api } from '../api/client.ts';
import { weiToEth } from '../amounts.ts';
import { useRole } from '../useCredentials.ts';
import type { Proposal } from '../types/index.ts';

interface ProposalCardProps {
  proposal: Proposal;
  onUpdated: (updated: Proposal) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
  executionMode?: 'simulated' | 'sepolia';
}

export const ProposalCard: React.FC<ProposalCardProps> = ({
  proposal,
  onUpdated,
  onOpenAudit,
  onOpenDetails,
  executionMode,
}) => {
  const hasRequiredRole = useRole('proposer');
  const [evaluating, setEvaluating] = useState(false);
  const [signing, setSigning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleEvaluate = async () => {
    setEvaluating(true);
    setActionError(null);
    try {
      const updated = await api.evaluateProposal(proposal.id);
      onUpdated(updated);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Evaluation failed');
    } finally {
      setEvaluating(false);
    }
  };

  const handleSign = async () => {
    setSigning(true);
    setActionError(null);
    try {
      const updated = await api.signProposal(proposal.id);
      onUpdated(updated);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Signing rejected');
    } finally {
      setSigning(false);
    }
  };

  // UI guidance only; backend authorization remains authoritative.
  const automatic = proposal.status === 'ALLOWED' && proposal.auto_execution_enabled &&
    /^\d+$/.test(proposal.amount_wei ?? '') &&
    /^\d+$/.test(proposal.auto_execution_max_wei ?? '') &&
    BigInt(proposal.amount_wei) <= BigInt(proposal.auto_execution_max_wei!);
  const isSignable = !automatic &&
    (proposal.status === 'ALLOWED' || proposal.status === 'APPROVED');
  const isResumable = proposal.status === 'SIGNED';
  const isBlocked = proposal.status === 'BLOCKED';
  const isEscalated = proposal.status === 'ESCALATED';
  const reasons = proposal.policy_decision?.reason_codes ?? [];

  return (
    <article className="glass-panel proposal-card proposal-card-compact" aria-label={`Proposal ${proposal.id.slice(0, 8)}`}>
      <header className="proposal-card-heading">
        <div className="proposal-card-identity">
          <span className="proposal-card-id">#{proposal.id.slice(0, 8)}</span>
          <StatusBadge status={proposal.status} />
        </div>
        <time className="proposal-card-date" dateTime={proposal.created_at}>
          {new Date(proposal.created_at).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
          })}
        </time>
      </header>

      <dl className="proposal-card-facts">
        <div className="proposal-card-amount">
          <dt>Amount</dt>
          <dd>{proposal.amount_eth} <span>ETH</span></dd>
        </div>
        <div className="proposal-card-recipient">
          <dt>Recipient</dt>
          <dd>{proposal.recipient}</dd>
        </div>
        <div>
          <dt>Network</dt>
          <dd>{proposal.chain_id === 11155111 ? 'Ethereum Sepolia' : `Chain ${proposal.chain_id}`}</dd>
        </div>
      </dl>

      <p className="proposal-card-prompt">{proposal.prompt}</p>
      {proposal.provenance === 'DETERMINISTIC_MANDATE' && <p className="proposal-card-context">Standing treasury mandate · version {proposal.mandate_version} · not a user-entered prompt</p>}

      {proposal.policy_decision && (
        <div className="proposal-card-policy">
          <span>Policy decision</span>
          <DecisionBadge decision={proposal.policy_decision.decision} showReasons={false} />
          {reasons.length > 0 && (
            <details className="proposal-card-reasons">
              <summary>View reasons ({reasons.length})</summary>
              <ul>{reasons.map((code, index) => <li key={`${code}-${index}`}>{humanizeEvent(code)}</li>)}</ul>
            </details>
          )}
        </div>
      )}

      {proposal.transaction?.tx_hash && (
        <div className="proposal-card-broadcast">
          <span>{proposal.transaction.execution_mode === 'simulated' ? 'Simulated · not broadcast' : proposal.transaction.execution_mode === 'sepolia' ? ({ UNCERTAIN: 'Sepolia · outcome uncertain', CONFIRMED: 'Sepolia · confirmed (1 receipt, not finality)', REVERTED: 'Sepolia · reverted', SUBMITTED: 'Sepolia · submitted, awaiting receipt', SIGNED: 'Sepolia · signed, not confirmed', SIMULATED: 'Mode mismatch · do not submit' }[proposal.transaction.execution_outcome ?? 'SIGNED']) : 'Transaction · mode unverified'}: {proposal.transaction.tx_hash.slice(0, 12)}…</span>
          {proposal.chain_id === 11155111 && proposal.transaction.execution_mode === 'sepolia' && (
            <a href={`https://sepolia.etherscan.io/tx/${proposal.transaction.tx_hash}`}
              target="_blank" rel="noopener noreferrer">
              View on Etherscan <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      )}

      {actionError && <p className="proposal-card-error" role="alert">{actionError}</p>}
      {proposal.auto_execution_enabled && proposal.auto_execution_max_wei &&
        <details className="proposal-card-context">
          <summary>Auto-execution limit: {weiToEth(proposal.auto_execution_max_wei)} ETH</summary>
          <p>Further restricted by policy, allowlist, budget, and security checks.</p>
        </details>}
      {automatic && <p className="required-role-note" role="status">
        Automatic execution has not completed. No payment is confirmed. Check the recipient
        allowlist, current policy, and pending executions before reevaluating this proposal.
      </p>}

      {(isSignable || isResumable || proposal.status === 'PROPOSED') && <p className="required-role-note">{hasRequiredRole ? 'Evaluation and submission permissions verified.' : 'Requires Proposer, or Demo administrator in simulation. Connect it using Switch role.'}</p>}
      <footer className="proposal-card-footer">
        <div className="proposal-card-actions">
          <button className="btn btn-outline" onClick={() => onOpenDetails(proposal)}>
            <FileText size={15} aria-hidden="true" /> Details
          </button>
          <button className="btn btn-outline" onClick={() => onOpenAudit(proposal.correlation_id)}>
            <History size={15} aria-hidden="true" /> Audit trail
          </button>
        </div>
        <div className="proposal-card-actions">
          {(proposal.status === 'PROPOSED' || automatic) && (
            <button className="btn btn-primary" onClick={handleEvaluate} disabled={evaluating || !hasRequiredRole}>
              <ShieldCheck size={15} aria-hidden="true" />
              {evaluating ? 'Checking…' : automatic ? 'Recheck automatic execution' : 'Evaluate policy'}
            </button>
          )}
          {isSignable && (
            <button className="btn btn-primary" onClick={handleSign} disabled={signing || !hasRequiredRole}>
              <Lock size={15} aria-hidden="true" />
              {signing ? 'Signing…' : executionMode === 'simulated' ? 'Sign & simulate' : executionMode === 'sepolia' ? 'Sign & broadcast' : 'Sign & submit'}
            </button>
          )}
          {isResumable && (
            <button className="btn btn-outline" onClick={handleSign} disabled={signing || !hasRequiredRole}>
              {signing ? 'Reconciling…' : 'Reconcile & retry same transaction'}
            </button>
          )}
          {isEscalated && (
            <span className="proposal-card-hold">
              <Clock size={15} aria-hidden="true" /> Human approval required
            </span>
          )}
          {isBlocked && (
            <span className="proposal-card-blocked">
              <Lock size={15} aria-hidden="true" /> Signing blocked by policy
            </span>
          )}
        </div>
      </footer>
    </article>
  );
};
