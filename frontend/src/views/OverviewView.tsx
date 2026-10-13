import React from 'react';
import {
  ShieldAlert,
  Clock,
  CheckCircle2,
  Send,
  ArrowRight,
  UserCheck,
} from 'lucide-react';
import { AgentPromptBox } from '../components/AgentPromptBox.tsx';
import { ProposalCard } from '../components/ProposalCard.tsx';
import { PolicyCard } from '../components/PolicyCard.tsx';
import type { PendingApproval, Policy, Proposal } from '../types/index.ts';

interface OverviewViewProps {
  proposals: Proposal[];
  activePolicy: Policy | null;
  pendingApprovals: PendingApproval[];
  onProposalCreated: (proposal: Proposal) => void;
  onProposalUpdated: (proposal: Proposal) => void;
  onPolicyUpdated: (policy: Policy) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
  onSelectApproval: (approval: PendingApproval) => void;
  onNavigateToTab: (tab: 'proposals' | 'approvals' | 'policies' | 'audit') => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  proposals,
  activePolicy,
  pendingApprovals,
  onProposalCreated,
  onProposalUpdated,
  onPolicyUpdated,
  onOpenAudit,
  onOpenDetails,
  onSelectApproval,
  onNavigateToTab,
}) => {
  const allowedCount = proposals.filter((p) => p.status === 'ALLOWED' || p.status === 'SUBMITTED' || p.status === 'CONFIRMED').length;
  const escalatedCount = proposals.filter((p) => p.status === 'ESCALATED').length;
  const blockedCount = proposals.filter((p) => p.status === 'BLOCKED').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Pending Approvals Urgent Banner */}
      {pendingApprovals.length > 0 && (
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, rgba(217, 119, 6, 0.1) 100%)',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            borderRadius: '12px',
            padding: '16px 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
            boxShadow: 'var(--glow-amber)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '8px',
                background: 'rgba(245, 158, 11, 0.25)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <UserCheck size={22} color="var(--color-amber)" />
            </div>
            <div>
              <h4 style={{ fontSize: '1rem', fontWeight: 600, color: '#fbbf24' }}>
                {pendingApprovals.length} Proposal{pendingApprovals.length > 1 ? 's' : ''} Awaiting Human Sign-off
              </h4>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                High-value actions escalated above policy threshold. Private keys locked until explicit approval.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              className="btn btn-emerald"
              style={{ padding: '8px 16px', fontSize: '0.85rem' }}
              onClick={() => onSelectApproval(pendingApprovals[0])}
            >
              Review Action
            </button>
            <button
              className="btn btn-outline"
              style={{ padding: '8px 14px', fontSize: '0.85rem' }}
              onClick={() => onNavigateToTab('approvals')}
            >
              View Queue ({pendingApprovals.length})
            </button>
          </div>
        </div>
      )}

      {/* KPI Stats Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px',
        }}
      >
        <div className="glass-panel" style={{ padding: '18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 600, textTransform: 'uppercase' }}>
              Total Proposals
            </span>
            <Send size={18} color="var(--color-blue)" />
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 700, color: '#fff', marginTop: '10px' }}>
            {proposals.length}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Natural language & structured inputs
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 600, textTransform: 'uppercase' }}>
              Allowed / Broadcasted
            </span>
            <CheckCircle2 size={18} color="var(--color-emerald)" />
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--color-emerald)', marginTop: '10px' }}>
            {allowedCount}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Passed deterministic checks
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 600, textTransform: 'uppercase' }}>
              Escalations
            </span>
            <Clock size={18} color="var(--color-amber)" />
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--color-amber)', marginTop: '10px' }}>
            {escalatedCount}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Exceeded threshold &bull; human-in-the-loop
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 600, textTransform: 'uppercase' }}>
              Blocked Attacks / Violations
            </span>
            <ShieldAlert size={18} color="var(--color-rose)" />
          </div>
          <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--color-rose)', marginTop: '10px' }}>
            {blockedCount}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Zero signing &bull; fail-closed enforcement
          </div>
        </div>
      </div>

      {/* Main Agent Interaction Box */}
      <AgentPromptBox onProposalCreated={onProposalCreated} />

      {/* Split section: Active Policy & Recent Proposals */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
        <div>
          <PolicyCard policy={activePolicy} onPolicyUpdated={onPolicyUpdated} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Recent Agent Activity</h3>
            <button
              className="btn btn-outline"
              style={{ padding: '4px 10px', fontSize: '0.78rem' }}
              onClick={() => onNavigateToTab('proposals')}
            >
              <span>View All ({proposals.length})</span>
              <ArrowRight size={12} />
            </button>
          </div>

          {proposals.length === 0 ? (
            <div className="glass-panel" style={{ padding: '32px', textAlign: 'center', color: 'var(--text-dim)' }}>
              No proposals recorded yet. Use the prompt box above to propose your first action.
            </div>
          ) : (
            proposals.slice(0, 3).map((proposal) => (
              <ProposalCard
                key={proposal.id}
                proposal={proposal}
                onUpdated={onProposalUpdated}
                onOpenAudit={onOpenAudit}
                onOpenDetails={onOpenDetails}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
};
