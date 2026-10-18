import React, { useState } from 'react';
import { UserCheck, ShieldAlert, CheckCircle2, XCircle, AlertTriangle, X } from 'lucide-react';
import { api } from '../api/client.ts';
import { useRole } from '../useCredentials.ts';
import type { PendingApproval } from '../types/index.ts';

interface ApprovalModalProps {
  approval: PendingApproval;
  onClose: () => void;
  onDecided: () => void;
}

export const ApprovalModal: React.FC<ApprovalModalProps> = ({
  approval,
  onClose,
  onDecided,
}) => {
  const hasRequiredRole = useRole('approver');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDecision = async (decision: 'APPROVE' | 'REJECT') => {
    if (!hasRequiredRole) { setError('Human approver credential required. Connect it using Switch role.'); return; }
    setLoading(true);
    setError(null);
    try {
      await api.decideApproval(approval.id, decision);
      onDecided();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Decision failed');
    } finally {
      setLoading(false);
    }
  };

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
      <div className="glass-panel" style={{ width: '100%', maxWidth: '560px', padding: '24px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(245, 158, 11, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid rgba(245, 158, 11, 0.3)',
              }}
            >
              <UserCheck size={20} color="var(--color-amber)" />
            </div>
            <div>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Human Authorization Gate</h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Explicit sign-off required for escalated high-value actions
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

        {/* Action Details Card */}
        <div
          style={{
            background: 'var(--bg-subtle)',
            border: '1px solid var(--border-light)',
            borderRadius: '10px',
            padding: '16px',
            marginBottom: '16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: 'var(--color-amber)', fontSize: '0.85rem', fontWeight: 600 }}>
            <AlertTriangle size={15} />
            <span>Exact Transaction Action Bound to Digest:</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.85rem' }}>
            <div>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Destination Recipient</span>
              <span className="font-mono" style={{ color: 'var(--color-cyan)', fontSize: '0.82rem', wordBreak: 'break-all' }}>
                {approval.proposal?.recipient || 'N/A'}
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Requested Amount</span>
                <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-main)' }}>
                  {approval.proposal?.amount_eth || '0'} ETH
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Target Chain</span>
                <span style={{ color: 'var(--text-muted)' }}>Sepolia (11155111)</span>
              </div>
            </div>

            <div>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Cryptographic Action Digest (SHA-256)</span>
              <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
                {approval.action_digest}
              </span>
            </div>

            <div>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem', display: 'block' }}>Expires At</span>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                {new Date(approval.expires_at).toLocaleString()}
              </span>
            </div>
          </div>
        </div>

        <p style={{ marginBottom: '20px', color: 'var(--text-muted)', fontSize: '.9rem' }}>
          Approval uses the separate human-approver credential, or Demo administrator in the isolated simulation profile, configured in API key settings.
          The backend records the authenticated identity. This authorization expires at the time shown above.
        </p>

        <p className="required-role-note">{hasRequiredRole ? 'Approval permission verified for the connected credential.' : 'Approve and reject require Human approver, or Demo administrator in simulation. Connect it using Switch role.'}</p>
        {/* Error message */}
        {error && (
          <div
            style={{
              padding: '10px 14px',
              borderRadius: '8px',
              background: 'rgba(244, 63, 94, 0.1)',
              border: '1px solid rgba(244, 63, 94, 0.3)',
              color: '#fb7185',
              fontSize: '0.85rem',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '16px',
            }}
          >
            <ShieldAlert size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="btn btn-rose"
            onClick={() => handleDecision('REJECT')}
            disabled={loading || !hasRequiredRole}
          >
            <XCircle size={16} />
            <span>Reject Proposal</span>
          </button>

          <button
            type="button"
            className="btn btn-emerald"
            onClick={() => handleDecision('APPROVE')}
            disabled={loading || !hasRequiredRole}
          >
            <CheckCircle2 size={16} />
            <span>Approve Authorization</span>
          </button>
        </div>
      </div>
    </div>
  );
};
