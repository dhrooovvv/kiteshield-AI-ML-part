import React, { useState } from 'react';
import {
  ExternalLink,
  ShieldCheck,
  History,
  Lock,
  Clock,
  CheckCircle,
  FileText,
} from 'lucide-react';
import { DecisionBadge } from './DecisionBadge.tsx';
import { StatusBadge } from './StatusBadge.tsx';
import { api } from '../api/client.ts';
import type { Proposal } from '../types/index.ts';

interface ProposalCardProps {
  proposal: Proposal;
  onUpdated: (updated: Proposal) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
}

export const ProposalCard: React.FC<ProposalCardProps> = ({
  proposal,
  onUpdated,
  onOpenAudit,
  onOpenDetails,
}) => {
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

  const isSignable = proposal.status === 'ALLOWED' || proposal.status === 'APPROVED';
  const isBlocked = proposal.status === 'BLOCKED';
  const isEscalated = proposal.status === 'ESCALATED';
  const isSubmitted = proposal.status === 'SUBMITTED' || proposal.status === 'CONFIRMED';

  return (
    <div
      className="glass-panel"
      style={{
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        borderLeft: isBlocked
          ? '4px solid var(--color-rose)'
          : isEscalated
          ? '4px solid var(--color-amber)'
          : isSignable
          ? '4px solid var(--color-emerald)'
          : isSubmitted
          ? '4px solid var(--color-cyan)'
          : '4px solid var(--color-blue)',
      }}
    >
      {/* Top Header: ID, Date, Badges */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className="font-mono" style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-muted)' }}>
            #{proposal.id.slice(0, 8)}
          </span>
          <StatusBadge status={proposal.status} />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <DecisionBadge
            decision={proposal.policy_decision?.decision}
            reasons={proposal.policy_decision?.reason_codes}
            showReasons={false}
          />
        </div>
      </div>

      {/* Prompt summary */}
      <div
        style={{
          background: 'var(--bg-subtle)',
          padding: '10px 14px',
          borderRadius: '8px',
          border: '1px solid var(--border-light)',
          fontSize: '0.88rem',
          color: '#e2e8f0',
        }}
      >
        <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: 600 }}>
          Agent Prompt
        </div>
        &ldquo;{proposal.prompt}&rdquo;
      </div>

      {/* Key Details Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px',
          fontSize: '0.85rem',
        }}
      >
        <div>
          <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Destination Address</span>
          <span className="font-mono" style={{ color: 'var(--color-cyan)', fontSize: '0.8rem', wordBreak: 'break-all' }}>
            {proposal.recipient}
          </span>
        </div>

        <div>
          <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Transfer Amount</span>
          <span style={{ fontWeight: 700, color: '#fff', fontSize: '1rem' }}>
            {proposal.amount_eth} ETH
          </span>
          <span className="font-mono" style={{ color: 'var(--text-dim)', fontSize: '0.72rem', display: 'block' }}>
            ({proposal.amount_wei} wei)
          </span>
        </div>

        <div>
          <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Target Chain</span>
          <span style={{ color: 'var(--text-muted)' }}>
            Ethereum Sepolia (11155111)
          </span>
        </div>
      </div>

      {/* Decision Reason Codes (if evaluated) */}
      {proposal.policy_decision?.reason_codes && proposal.policy_decision.reason_codes.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Policy Engine Reasons:</span>
          {proposal.policy_decision.reason_codes.map((code, idx) => (
            <span
              key={idx}
              className="font-mono"
              style={{
                fontSize: '0.72rem',
                background: isBlocked
                  ? 'rgba(244, 63, 94, 0.15)'
                  : isEscalated
                  ? 'rgba(245, 158, 11, 0.15)'
                  : 'rgba(16, 185, 129, 0.15)',
                color: isBlocked
                  ? '#fb7185'
                  : isEscalated
                  ? '#fbbf24'
                  : '#34d399',
                border: `1px solid ${
                  isBlocked
                    ? 'rgba(244, 63, 94, 0.3)'
                    : isEscalated
                    ? 'rgba(245, 158, 11, 0.3)'
                    : 'rgba(16, 185, 129, 0.3)'
                }`,
                padding: '2px 8px',
                borderRadius: '6px',
              }}
            >
              {code}
            </span>
          ))}
        </div>
      )}

      {/* Transaction Broadcast Link */}
      {proposal.transaction?.tx_hash && (
        <div
          style={{
            background: 'rgba(0, 242, 254, 0.08)',
            border: '1px solid rgba(0, 242, 254, 0.25)',
            padding: '8px 12px',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CheckCircle size={15} color="var(--color-cyan)" />
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Broadcast to Sepolia:</span>
            <span className="font-mono" style={{ fontSize: '0.8rem', color: '#fff' }}>
              {proposal.transaction.tx_hash.slice(0, 16)}...
            </span>
          </div>
          <a
            href={`https://sepolia.etherscan.io/tx/${proposal.transaction.tx_hash}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: 'var(--color-cyan)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '0.78rem',
              textDecoration: 'none',
              fontWeight: 600,
            }}
          >
            <span>Etherscan</span>
            <ExternalLink size={12} />
          </a>
        </div>
      )}

      {/* Error message */}
      {actionError && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: '6px',
            background: 'rgba(244, 63, 94, 0.1)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: '#fb7185',
            fontSize: '0.8rem',
          }}
        >
          {actionError}
        </div>
      )}

      {/* Actions Toolbar */}
      <div
        style={{
          borderTop: '1px solid var(--border-light)',
          paddingTop: '12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '10px',
        }}
      >
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className="btn btn-outline"
            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            onClick={() => onOpenDetails(proposal)}
          >
            <FileText size={14} />
            <span>Details</span>
          </button>

          <button
            className="btn btn-outline"
            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            onClick={() => onOpenAudit(proposal.correlation_id)}
          >
            <History size={14} />
            <span>Audit Trail</span>
          </button>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          {proposal.status === 'PROPOSED' && (
            <button
              className="btn btn-primary"
              style={{ padding: '6px 16px', fontSize: '0.8rem' }}
              onClick={handleEvaluate}
              disabled={evaluating}
            >
              <ShieldCheck size={14} />
              <span>{evaluating ? 'Evaluating...' : 'Evaluate Policy'}</span>
            </button>
          )}

          {isSignable && (
            <button
              className="btn btn-emerald"
              style={{ padding: '6px 16px', fontSize: '0.8rem' }}
              onClick={handleSign}
              disabled={signing}
            >
              <Lock size={14} />
              <span>{signing ? 'Signing with Isolated Key...' : 'Sign & Broadcast'}</span>
            </button>
          )}

          {isEscalated && (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '0.8rem',
                color: 'var(--color-amber)',
                fontWeight: 600,
              }}
            >
              <Clock size={14} />
              <span>Pending Human Authorization</span>
            </div>
          )}

          {isBlocked && (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: '0.8rem',
                color: 'var(--color-rose)',
                fontWeight: 600,
              }}
            >
              <Lock size={14} />
              <span>Signing Prohibited by Security Policy</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
