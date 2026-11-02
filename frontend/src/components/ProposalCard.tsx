import React, { useState } from 'react';
import {
  ExternalLink,
  ShieldCheck,
  History,
  Lock,
  Clock,
  FileText,
} from 'lucide-react';
import { StatusBadge } from './StatusBadge.tsx';
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
  const isVault = proposal.payment_backend === 'VAULT';
  const automatic = !isVault && proposal.status === 'ALLOWED' && proposal.auto_execution_enabled &&
    /^\d+$/.test(proposal.amount_wei ?? '') &&
    /^\d+$/.test(proposal.auto_execution_max_wei ?? '') &&
    BigInt(proposal.amount_wei) <= BigInt(proposal.auto_execution_max_wei!);
  const isSignable = !isVault && !automatic &&
    (proposal.status === 'ALLOWED' || proposal.status === 'APPROVED');
  const isResumable = !isVault && proposal.status === 'SIGNED';
  const isBlocked = proposal.status === 'BLOCKED';
  const isEscalated = proposal.status === 'ESCALATED';
  const sourceTitle = isVault ? 'Guarded vault · administrator session' : proposal.provenance === 'invoice_intake'
    ? 'Invoice intake · verified vendor registry'
    : proposal.provenance === 'DETERMINISTIC_MANDATE'
      ? 'Treasury sweep · standing mandate' : 'Payment request';
  const transaction = proposal.transaction;
  const explorerUrl = proposal.chain_id === 11155111 && transaction?.execution_mode === 'sepolia' &&
    /^0x[0-9a-fA-F]{64}$/.test(transaction.tx_hash ?? '') &&
    ['SUBMITTED', 'CONFIRMED', 'REVERTED', 'UNCERTAIN'].includes(transaction.execution_outcome ?? '')
    ? `https://sepolia.etherscan.io/tx/${transaction.tx_hash}` : null;
  const missingTransactionStatus = executionMode === 'simulated' || transaction?.execution_mode === 'simulated'
    ? 'Simulation · no on-chain broadcast'
    : ['SUBMITTED', 'CONFIRMED', 'SIGNED', 'SIGNING', 'TX_FAILED'].includes(proposal.status)
      ? 'Transaction evidence unavailable' : 'Not submitted · no on-chain transaction';

  const executionActions = <div className="proposal-card-actions">
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
        </div>;

  return (
    <article className="glass-panel proposal-card proposal-card-compact" aria-label={`Proposal ${proposal.id.slice(0, 8)}`}>
      <header className="proposal-card-heading">
        <div className="proposal-card-identity">
          <StatusBadge status={proposal.status} />
          <span className="proposal-card-id" title={proposal.id}>#{proposal.id.slice(0, 8)}</span>
        </div>
        <time className="proposal-card-date" dateTime={proposal.created_at}>
          {new Date(proposal.created_at).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
          })}
        </time>
      </header>

      <h3 className="proposal-card-source">{sourceTitle}</h3>
      {isVault && <p className="proposal-card-context">Managed in Autonomous tasks. The task binds the vault call, allowance and receipt.</p>}
      {proposal.provenance === 'DETERMINISTIC_MANDATE' && proposal.mandate_version != null &&
        <p className="proposal-card-context">Mandate version {proposal.mandate_version}</p>}

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

      {proposal.transaction?.tx_hash ? (
        <div className="proposal-card-broadcast">
          <span>{proposal.transaction.execution_mode === 'simulated' ? 'Simulated · not broadcast' : proposal.transaction.execution_mode === 'sepolia' ? ({ UNCERTAIN: 'Sepolia · outcome uncertain', CONFIRMED: 'Sepolia · confirmed (1 receipt, not finality)', REVERTED: 'Sepolia · reverted', SUBMITTED: 'Sepolia · submitted, awaiting receipt', SIGNED: 'Sepolia · signed, not confirmed', SIMULATED: 'Mode mismatch · do not submit' }[proposal.transaction.execution_outcome ?? 'SIGNED']) : 'Transaction · mode unverified'}</span>
          <span className="proposal-card-hash" title={proposal.transaction.tx_hash}>{proposal.transaction.tx_hash.slice(0, 10)}…{proposal.transaction.tx_hash.slice(-6)}</span>
          {explorerUrl && (
            <a href={explorerUrl}
              target="_blank" rel="noopener noreferrer">
              View on Etherscan <ExternalLink size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      ) : (
        <div className="proposal-card-broadcast proposal-card-awaiting">
          <span>{missingTransactionStatus}</span>
          <span className="proposal-card-hash">No transaction hash available</span>
          {executionActions}
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

      {(isSignable || isResumable || proposal.status === 'PROPOSED') && !hasRequiredRole && <p className="required-role-note">Proposer required. Connect using Switch role.</p>}
      {proposal.transaction?.tx_hash && (isResumable || isSignable || automatic) && executionActions}
      <footer className="proposal-card-footer">
        <div className="proposal-card-actions">
          <button className="btn btn-outline" onClick={() => onOpenDetails(proposal)}>
            <FileText size={15} aria-hidden="true" /> Details
          </button>
          <button className="btn btn-outline" onClick={() => onOpenAudit(proposal.correlation_id)}>
            <History size={15} aria-hidden="true" /> Audit trail
          </button>
        </div>

      </footer>
    </article>
  );
};
