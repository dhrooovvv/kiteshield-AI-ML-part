import React from 'react';
import { UserCheck, CheckCircle2, Clock } from 'lucide-react';
import type { PendingApproval } from '../types/index.ts';

interface ApprovalsViewProps {
  pendingApprovals: PendingApproval[];
  onSelectApproval: (approval: PendingApproval) => void;
}

export const ApprovalsView: React.FC<ApprovalsViewProps> = ({
  pendingApprovals,
  onSelectApproval,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Human Authorization Queue</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Transactions escalated beyond autonomous threshold. Cryptographically bound approval required before capability token issuance.
        </p>
      </div>

      {pendingApprovals.length === 0 ? (
        <div
          className="glass-panel"
          style={{
            padding: '60px 20px',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <div
            style={{
              width: '54px',
              height: '54px',
              borderRadius: '50%',
              background: 'rgba(16, 185, 129, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid rgba(16, 185, 129, 0.3)',
            }}
          >
            <CheckCircle2 size={28} color="var(--color-emerald)" />
          </div>
          <h3 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Queue Clear</h3>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '420px' }}>
            No actions are currently awaiting human review. Autonomous policies are operating within their defined bounds.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {pendingApprovals.map((appReq) => (
            <div
              key={appReq.id}
              className="glass-panel"
              style={{
                padding: '20px',
                borderLeft: '4px solid var(--color-amber)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '16px',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '640px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="badge badge-escalate">ESCALATION # {appReq.id.slice(0, 8)}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.78rem', color: 'var(--text-dim)' }}>
                    <Clock size={13} />
                    <span>Expires: {new Date(appReq.expires_at).toLocaleTimeString()}</span>
                  </div>
                </div>

                <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fff' }}>
                  {appReq.proposal?.prompt || 'Escalated proposal action'}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-dim)', fontSize: '0.72rem', display: 'block' }}>Destination:</span>
                    <span className="font-mono" style={{ color: 'var(--color-cyan)', fontSize: '0.8rem' }}>
                      {appReq.proposal?.recipient || 'N/A'}
                    </span>
                  </div>

                  <div>
                    <span style={{ color: 'var(--text-dim)', fontSize: '0.72rem', display: 'block' }}>Amount:</span>
                    <span style={{ fontWeight: 700, color: '#fff', fontSize: '1rem' }}>
                      {appReq.proposal?.amount_eth || '0'} ETH
                    </span>
                  </div>
                </div>

                <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                  Action Digest (SHA-256):{' '}
                  <span className="font-mono" style={{ color: 'var(--text-muted)' }}>
                    {appReq.action_digest.slice(0, 32)}...
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  className="btn btn-emerald"
                  onClick={() => onSelectApproval(appReq)}
                  style={{ padding: '8px 18px' }}
                >
                  <UserCheck size={16} />
                  <span>Review & Decide</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
