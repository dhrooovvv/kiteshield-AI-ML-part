import React from 'react';
import { FileText, X } from 'lucide-react';
import { DecisionBadge } from './DecisionBadge.tsx';
import { StatusBadge } from './StatusBadge.tsx';
import type { Proposal } from '../types/index.ts';

interface ProposalDetailModalProps {
  proposal: Proposal;
  onClose: () => void;
  onOpenAudit: (correlationId: string) => void;
}

export const ProposalDetailModal: React.FC<ProposalDetailModalProps> = ({
  proposal,
  onClose,
  onOpenAudit,
}) => {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
      }}
    >
      <div
        className="glass-panel"
        style={{
          width: '100%',
          maxWidth: '680px',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          padding: '24px',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(59, 130, 246, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid rgba(59, 130, 246, 0.3)',
              }}
            >
              <FileText size={20} color="var(--color-blue)" />
            </div>
            <div>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Proposal Inspection</h3>
              <p className="font-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                UUID: {proposal.id}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-dim)',
              cursor: 'pointer',
              padding: '4px',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Status & Decision header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'var(--bg-subtle)',
              padding: '12px 16px',
              borderRadius: '8px',
              border: '1px solid var(--border-light)',
            }}
          >
            <div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'block' }}>Lifecycle Status</span>
              <StatusBadge status={proposal.status} />
            </div>
            <div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'block' }}>Policy Decision</span>
              <DecisionBadge decision={proposal.policy_decision?.decision} />
            </div>
          </div>

          {/* Action Parameters */}
          <div style={{ background: 'var(--bg-subtle)', padding: '16px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
            <h4 style={{ fontSize: '0.85rem', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: '12px', fontWeight: 600 }}>
              Transaction Parameters
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', fontSize: '0.85rem' }}>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Amount in ETH</span>
                <span style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff' }}>{proposal.amount_eth} ETH</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Amount in Wei (Exact Integer)</span>
                <span className="font-mono" style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{proposal.amount_wei}</span>
              </div>
              <div style={{ gridColumn: 'span 2' }}>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Recipient Address</span>
                <span className="font-mono" style={{ color: 'var(--color-cyan)', fontSize: '0.82rem', wordBreak: 'break-all' }}>
                  {proposal.recipient}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Target Chain ID</span>
                <span style={{ color: 'var(--text-muted)' }}>{proposal.chain_id} (Sepolia)</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Asset Type</span>
                <span style={{ color: 'var(--text-muted)' }}>{proposal.asset_type}</span>
              </div>
            </div>
          </div>

          {/* Agent Prompt */}
          <div style={{ background: 'var(--bg-subtle)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-light)' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
              Original Agent Natural Language Prompt
            </span>
            <p style={{ fontSize: '0.88rem', color: '#e2e8f0' }}>&ldquo;{proposal.prompt}&rdquo;</p>
          </div>

          {/* Policy Evaluation Details */}
          {proposal.policy_decision && (
            <div style={{ background: 'var(--bg-subtle)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-light)' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
                Policy Evaluation (Version {proposal.policy_decision.policy_version})
              </span>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                {proposal.policy_decision.reason_codes.map((code, idx) => (
                  <span
                    key={idx}
                    className="font-mono"
                    style={{
                      fontSize: '0.75rem',
                      background: 'rgba(255, 255, 255, 0.08)',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      color: 'var(--color-cyan)',
                    }}
                  >
                    {code}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Transaction on-chain */}
          {proposal.transaction && (
            <div style={{ background: 'var(--bg-subtle)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-light)' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
                On-Chain Broadcast Details
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.85rem' }}>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>Tx Hash: </span>
                  <span className="font-mono" style={{ color: 'var(--color-cyan)' }}>
                    {proposal.transaction.tx_hash || 'Pending'}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>Status: </span>
                  <span style={{ color: '#fff', fontWeight: 600 }}>{proposal.transaction.status}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: '16px', marginTop: '16px', display: 'flex', justifyContent: 'space-between' }}>
          <button
            className="btn btn-outline"
            onClick={() => {
              onClose();
              onOpenAudit(proposal.correlation_id);
            }}
          >
            Open Audit Trail
          </button>
          <button className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
