import React from 'react';
import { UserCheck, CheckCircle2, ShieldAlert } from 'lucide-react';
import type { PendingApproval, PromptReviewEvent } from '../types/index.ts';

interface ApprovalsViewProps {
  pendingApprovals: PendingApproval[];
  promptReviews: PromptReviewEvent[];
  pendingApprovalsError: string | null;
  promptReviewsError: string | null;
  onSelectApproval: (approval: PendingApproval) => void;
  onOpenAudit: (correlationId: string) => void;
  loading: boolean;
}

export const ApprovalsView: React.FC<ApprovalsViewProps> = ({ pendingApprovals, promptReviews, pendingApprovalsError, promptReviewsError, onSelectApproval, onOpenAudit, loading }) => {
  const hasErrors = Boolean(pendingApprovalsError || promptReviewsError);
  const hasItems = pendingApprovals.length > 0 || promptReviews.length > 0;
  return (
    <div className="approvals-page">
      {loading && <p className="approvals-loading" role="status">Refreshing approval and review records…</p>}
      {hasErrors && <div className="state-panel state-error"><ShieldAlert size={20} /><div><strong>Unable to load the complete review queue</strong><p>{pendingApprovalsError || promptReviewsError}</p></div></div>}
      {!hasErrors && !hasItems && !loading && <div className="approvals-empty"><CheckCircle2 size={24} /><h3>Queue clear</h3><p>No pending transaction approvals or security-review records.</p></div>}
      {!hasErrors && hasItems && <div className="approvals-workspace">
        {pendingApprovals.length > 0 && <section className="approvals-section" aria-labelledby="transaction-approvals-heading">
          <header className="approvals-section-heading"><div><h2 id="transaction-approvals-heading">Transaction approvals</h2><p>Review the exact action before approving or rejecting it.</p></div><span>{pendingApprovals.length} awaiting decision</span></header>
          {pendingApprovals.map(request => <article className="approvals-record" key={request.id}>
            <div className="approvals-record-main approvals-transaction"><UserCheck size={18} /><div className="approvals-record-body">
              <h3>{request.proposal?.prompt || 'Escalated proposal action'}</h3>
              <p className="approvals-meta">Reference #{request.id.slice(0, 8)} · Expires <time dateTime={request.expires_at}>{new Date(request.expires_at).toLocaleString()}</time></p>
              <details className="approvals-details"><summary>Action details</summary><dl><div><dt>Recipient</dt><dd>{request.proposal?.recipient || 'Unavailable'}</dd></div><div><dt>Action digest (SHA-256)</dt><dd>{request.action_digest}</dd></div><div><dt>Approval reference</dt><dd>{request.id}</dd></div></dl></details>
            </div></div>
            <span className="approvals-amount">{request.proposal?.amount_eth ? `${request.proposal.amount_eth} ETH` : 'Amount unavailable'}</span>
            <button className="btn btn-emerald" onClick={() => onSelectApproval(request)}>Review &amp; Decide</button>
          </article>)}
        </section>}
        {promptReviews.length > 0 && <section className="approvals-section" aria-labelledby="security-reviews-heading">
          <header className="approvals-section-heading"><div><h2 id="security-reviews-heading">Prompt-security reviews</h2><p>Informational holds only. No proposal was created and no transaction can be approved from these records.</p></div><span>{promptReviews.length} held</span></header>
          {promptReviews.map(review => <article className="approvals-record" key={review.id}>
            <div className="approvals-record-main"><ShieldAlert size={18} /><div className="approvals-record-body"><h3>Detector disagreement</h3><p className="approvals-meta">Review required · Reference #{review.correlation_id.slice(0, 8)}</p><details className="approvals-details"><summary>Full reference</summary><p>{review.correlation_id}</p></details></div></div>
            <time className="approvals-date" dateTime={review.created_at}>{new Date(review.created_at).toLocaleString()}</time>
            <button className="btn btn-outline" onClick={() => onOpenAudit(review.correlation_id)}>View audit</button>
          </article>)}
          <p className="approvals-note">Prompt-review resolution is not available yet. These holds cannot authorize a transaction.</p>
        </section>}
      </div>}
    </div>
  );
};
