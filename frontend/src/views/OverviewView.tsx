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
import { PolicyCard } from '../components/PolicyCard.tsx';
import { DecisionBadge } from '../components/DecisionBadge.tsx';
import { StatusBadge } from '../components/StatusBadge.tsx';
import { countEscalations } from '../dashboardMetrics.ts';
import type { PendingApproval, Policy, Proposal, PromptReviewEvent } from '../types/index.ts';

interface OverviewViewProps {
  blockedAttemptsCount?: number;
  proposals: Proposal[];
  activePolicy: Policy | null;
  pendingApprovals: PendingApproval[];
  promptReviews: PromptReviewEvent[];
  onProposalCreated: (proposal: Proposal) => void;
  onPolicyUpdated: (policy: Policy) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
  onSelectApproval: (approval: PendingApproval) => void;
  onNavigateToTab: (tab: 'proposals' | 'approvals' | 'policies' | 'audit') => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  blockedAttemptsCount,
  proposals,
  activePolicy,
  pendingApprovals,
  promptReviews,
  onProposalCreated,
  onPolicyUpdated,
  onOpenAudit,
  onOpenDetails,
  onSelectApproval,
  onNavigateToTab,
}) => {
  const allowedCount = proposals.filter((p) => p.status === 'ALLOWED' || p.status === 'SUBMITTED' || p.status === 'CONFIRMED').length;
  const escalatedCount = countEscalations(proposals, promptReviews);
  const blockedCount = blockedAttemptsCount ?? proposals.filter((p) => p.status === 'BLOCKED').length;

  return (
    <div className="overview-page">
      {/* Pending Approvals Urgent Banner */}
      {pendingApprovals.length > 0 && (
        <div className="overview-approval-notice">
          <div className="overview-approval-heading">
            <UserCheck size={20} aria-hidden="true" />
            <div>
              <h4>
                {pendingApprovals.length} Proposal{pendingApprovals.length > 1 ? 's' : ''} Awaiting Human Sign-off
              </h4>
              <p>
                These proposals require human approval before execution.
              </p>
            </div>
          </div>

          <div className="overview-approval-actions">
            <button
              className="btn btn-emerald"
              onClick={() => onSelectApproval(pendingApprovals[0])}
            >
              Review Action
            </button>
            <button
              className="btn btn-outline"
              onClick={() => onNavigateToTab('approvals')}
            >
              View Queue ({pendingApprovals.length})
            </button>
          </div>
        </div>
      )}

      <div className="overview-metrics">
        {[
          { label: 'Total proposals', value: proposals.length, icon: Send, tone: 'neutral' },
          { label: 'Allowed / sent', value: allowedCount, icon: CheckCircle2, tone: 'allowed' },
          { label: 'Escalations', value: escalatedCount, icon: Clock, tone: 'escalated' },
          { label: 'Blocked', value: blockedCount, icon: ShieldAlert, tone: 'blocked' },
        ].map(({ label, value, icon: Icon, tone }) => (
          <div key={label} className={`overview-metric overview-metric-${tone}`}>
            <div><span>{label}</span><Icon size={17} aria-hidden="true" /></div>
            <strong>{value}</strong>
          </div>
        ))}
      </div>

      {promptReviews.length > 0 && (
        <div className="review-summary">
          <ShieldAlert size={19} aria-hidden="true" />
          <p><strong>{promptReviews.length} prompt security reviews</strong></p>
          <button className="btn btn-outline" onClick={() => onNavigateToTab('approvals')}>View reviews <ArrowRight size={14} /></button>
        </div>
      )}

      {/* The primary task and deterministic policy are peers in the dashboard hierarchy. */}
      <section className="overview-workspace">
        <AgentPromptBox onProposalCreated={onProposalCreated} />
        <PolicyCard policy={activePolicy} onPolicyUpdated={onPolicyUpdated} />

      {/* Recent activity is intentionally compact; the full proposal workflow remains on Proposals. */}
      <section className="activity-section">
        <div className="section-heading-row">
          <div>
            <h3>Recent Agent Activity</h3>
          </div>
          <button className="btn btn-outline" onClick={() => onNavigateToTab('proposals')}>
            <span>View all ({proposals.length})</span>
            <ArrowRight size={14} />
          </button>
        </div>
        <div className="activity-list">
          {proposals.length === 0 ? (
            <div className="activity-empty">
              No proposals recorded yet. Use the prompt box above to propose your first action.
            </div>
          ) : (
            proposals.slice(0, 3).map((proposal) => (
              <article
                key={proposal.id}
                className="activity-row"
              >
                <div className="activity-row-main">
                  <span className="font-mono activity-id">#{proposal.id.slice(0, 8)}</span>
                  <div className="activity-prompt">
                    <strong>{proposal.prompt}</strong>
                    <span>{proposal.recipient} · {proposal.amount_eth} ETH · {new Date(proposal.updated_at).toLocaleString()}{proposal.transaction?.execution_mode === 'simulated' ? ' · Simulated, not broadcast' : ''}</span>
                  </div>
                </div>
                <div className="activity-row-meta">
                  <StatusBadge status={proposal.status} />
                  <DecisionBadge decision={proposal.policy_decision?.decision} />
                  <button className="btn btn-outline activity-action" onClick={() => onOpenDetails(proposal)}>Details</button>
                  <button className="btn btn-outline activity-action" onClick={() => onOpenAudit(proposal.correlation_id)}>Audit</button>
                </div>
              </article>
            ))
          )}
        </div>
      </section>
      </section>
    </div>
  );
};
