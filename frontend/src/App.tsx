import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Header } from './components/Header.tsx';
import { Navigation, type NavTab } from './components/Navigation.tsx';
import { OverviewView } from './views/OverviewView.tsx';
import { ProposalsView } from './views/ProposalsView.tsx';
import { ApprovalsView } from './views/ApprovalsView.tsx';
import { PoliciesView } from './views/PoliciesView.tsx';
import { AuditView } from './views/AuditView.tsx';
import { ApprovalModal } from './components/ApprovalModal.tsx';
import { AuditTrailModal } from './components/AuditTrailModal.tsx';
import { ProposalDetailModal } from './components/ProposalDetailModal.tsx';
import { KiteShieldAPIError, api } from './api/client.ts';
import type { BackendHealth, PendingApproval, Policy, Proposal, PromptReviewEvent } from './types/index.ts';
import { countHumanAttentionItems } from './dashboardMetrics.ts';
import { refreshPaymentReceipts } from './paymentReceipts.ts';
import { PortfolioView } from './views/PortfolioView.tsx';
import { TreasuryView } from './views/TreasuryView.tsx';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavTab>('overview');
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [activePolicy, setActivePolicy] = useState<Policy | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [promptReviews, setPromptReviews] = useState<PromptReviewEvent[]>([]);
  const [blockedCount, setBlockedCount] = useState<number | undefined>(undefined);
  const [promptReviewsError, setPromptReviewsError] = useState<string | null>(null);
  const [pendingApprovalsError, setPendingApprovalsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const [refreshRevision, setRefreshRevision] = useState(0);
  const [portfolioRefreshRevision, setPortfolioRefreshRevision] = useState(0);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const refreshInFlight = useRef(false);
  const refreshRequested = useRef(false);

  // Modal states
  const [selectedApproval, setSelectedApproval] = useState<PendingApproval | null>(null);
  const [selectedAuditCid, setSelectedAuditCid] = useState<string | null>(null);
  const [selectedProposalForDetails, setSelectedProposalForDetails] = useState<Proposal | null>(null);

  const fetchAllData = useCallback(async function refreshData() {
    if (refreshInFlight.current) {
      refreshRequested.current = true;
      return;
    }
    refreshInFlight.current = true;
    setLoading(true);
    setGlobalError(null);
    try {
      const [healthResult, policyResult, proposalResult, approvalResult, reviewResult, countsResult] = await Promise.allSettled([
        api.checkHealth(), api.getActivePolicy(), api.listProposals(undefined, 50, 0),
        api.listPendingApprovals(), api.listPromptScreeningReviews(),
        api.getScreeningCounts(),
      ]);
      const failures: string[] = [];
      if (countsResult.status === 'fulfilled') setBlockedCount(countsResult.value.blocked_count);
      else failures.push('Blocked-attempt count');
      setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null);
      if (healthResult.status === 'rejected') failures.push('Service status');
      if (policyResult.status === 'fulfilled') setActivePolicy(policyResult.value);
      else if (policyResult.reason instanceof KiteShieldAPIError && policyResult.reason.status === 404) setActivePolicy(null);
      else failures.push('Active policy');
      if (proposalResult.status === 'fulfilled') {
        const receipts = await refreshPaymentReceipts(
          proposalResult.value.proposals, (id) => api.getTransaction(id),
        );
        setProposals(receipts.proposals);
        if (receipts.failed) failures.push('Transaction receipts (confirmation not verified)');
      }
      else failures.push('Proposals');
      if (approvalResult.status === 'fulfilled') {
        setPendingApprovals(approvalResult.value);
        setPendingApprovalsError(null);
      } else {
        setPendingApprovalsError('Transaction approvals could not be refreshed. Retry or check your API key.');
        failures.push('Transaction approvals');
      }
      if (reviewResult.status === 'fulfilled') {
        setPromptReviews(reviewResult.value);
        setPromptReviewsError(null);
      } else {
        setPromptReviewsError('Prompt reviews could not be refreshed. Retry or check your API key.');
        failures.push('Prompt reviews');
      }
      const authenticationFailed = [policyResult, proposalResult, approvalResult, reviewResult, countsResult].some(
        (result) => result.status === 'rejected' && result.reason instanceof KiteShieldAPIError && result.reason.status === 401
      );
      setGlobalError(authenticationFailed
        ? 'The backend is reachable, but authentication failed. Open API key and verify the credential for its matching role. Keys and verified roles are cleared when the page reloads.'
        : failures.length ? 'Could not refresh: ' + failures.join(', ') + '. Previously loaded data may be out of date. Check your connection and API key, then retry.' : null);
      if (!failures.length) setLastRefreshed(new Date().toLocaleTimeString());
      setRefreshRevision((value) => value + 1);
    } finally {
      refreshInFlight.current = false;
      setLoading(false);
      if (refreshRequested.current) {
        refreshRequested.current = false;
        queueMicrotask(() => { void refreshData(); });
      }
    }
  }, []);
  useEffect(() => api.subscribeScreeningEvents(() => { void fetchAllData(); }), [fetchAllData]);
  useEffect(() => {
    let isMounted = true;
    queueMicrotask(() => {
      if (isMounted) {
        void fetchAllData();
      }
    });
    // Poll every 10 seconds for real-time human approval & proposal updates
    const interval = setInterval(() => {
      if (isMounted) {
        void fetchAllData();
      }
    }, 10000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [fetchAllData]);

  // Handlers for state updates
  const handleManualRefresh = () => {
    setPortfolioRefreshRevision(value => value + 1);
    void fetchAllData();
  };
  const handleProposalCreated = (newProp: Proposal) => {
    setProposals((prev) => [newProp, ...prev]);
    fetchAllData();
  };

  const handleProposalUpdated = (updatedProp: Proposal) => {
    setProposals((prev) => prev.map((p) => (p.id === updatedProp.id ? updatedProp : p)));
    fetchAllData();
  };

  const handlePolicyUpdated = (newPolicy: Policy) => {
    setActivePolicy(newPolicy);
    fetchAllData();
  };

  const humanAttentionCount = countHumanAttentionItems(pendingApprovals, promptReviews);

  return (
    <div className="app-shell">
      <Navigation
        currentTab={currentTab}
        onTabChange={setCurrentTab}
        pendingApprovalsCount={pendingApprovals.length}
        promptReviewsCount={humanAttentionCount - pendingApprovals.length}
        totalProposalsCount={proposals.length}
      />
      <div className="app-main">
        <Header title={{ overview: 'Overview', proposals: 'Proposals', approvals: 'Human Approvals', policies: 'Policy Engine', audit: 'Audit Explorer', portfolio: 'Portfolio', treasury: 'Treasury Autopilot' }[currentTab]} health={health} onRefreshAll={handleManualRefresh} loading={loading} />

      {/* Global error banner if backend is unreachable */}
      {globalError && (
        <div
          style={{
            maxWidth: '1440px',
            margin: '16px auto 0',
            width: 'calc(100% - 48px)',
            background: 'rgba(244, 63, 94, 0.15)',
            border: '1px solid rgba(244, 63, 94, 0.4)',
            color: 'var(--color-rose)',
            padding: '12px 18px',
            borderRadius: '10px',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{globalError}</span>
          <button className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.75rem' }} onClick={fetchAllData}>
            Retry Connection
          </button>
        </div>
      )}

      {/* Main Content View Container */}
      <main className="content-shell">
        {currentTab !== 'portfolio' && currentTab !== 'approvals' && currentTab !== 'treasury' && <p className="refresh-status" role="status">{loading ? 'Refreshing data…' : lastRefreshed ? 'Last updated ' + lastRefreshed : 'Waiting for data'}</p>}
        {currentTab === 'overview' && (
          <OverviewView
            blockedAttemptsCount={blockedCount}
            proposals={proposals}
            activePolicy={activePolicy}
            pendingApprovals={pendingApprovals}
            promptReviews={promptReviews}
            onProposalCreated={handleProposalCreated}
            onPolicyUpdated={handlePolicyUpdated}
            onOpenAudit={(cid) => setSelectedAuditCid(cid)}
            onOpenDetails={(p) => setSelectedProposalForDetails(p)}
            onSelectApproval={(a) => setSelectedApproval(a)}
            onNavigateToTab={(t) => setCurrentTab(t)}
          />
        )}

        {currentTab === 'proposals' && (
          <ProposalsView
            executionMode={health?.execution_mode}
            proposals={proposals}
            onProposalCreated={handleProposalCreated}
            onProposalUpdated={handleProposalUpdated}
            onOpenAudit={(cid) => setSelectedAuditCid(cid)}
            onOpenDetails={(p) => setSelectedProposalForDetails(p)}
          />
        )}

        {currentTab === 'approvals' && (
          <ApprovalsView
            pendingApprovals={pendingApprovals}
            promptReviews={promptReviews}
            pendingApprovalsError={pendingApprovalsError}
            promptReviewsError={promptReviewsError}
            onSelectApproval={(a) => setSelectedApproval(a)}
            onOpenAudit={setSelectedAuditCid}
            loading={loading}
          />
        )}

        {currentTab === 'policies' && (
          <PoliciesView
            activePolicy={activePolicy}
            onPolicyUpdated={handlePolicyUpdated}
            refreshRevision={refreshRevision}
          />
        )}

        {currentTab === 'audit' && <AuditView refreshRevision={refreshRevision} />}
        {currentTab === 'portfolio' && <PortfolioView refreshRevision={portfolioRefreshRevision} />}
        {currentTab === 'treasury' && <TreasuryView refreshRevision={portfolioRefreshRevision} onOpenAudit={setSelectedAuditCid} onOpenDetails={setSelectedProposalForDetails} />}
      </main>

      {/* Modals */}
      {selectedApproval && (
        <ApprovalModal
          approval={selectedApproval}
          onClose={() => setSelectedApproval(null)}
          onDecided={fetchAllData}
        />
      )}

      {selectedAuditCid && (
        <AuditTrailModal
          correlationId={selectedAuditCid}
          onClose={() => setSelectedAuditCid(null)}
        />
      )}

      {selectedProposalForDetails && (
        <ProposalDetailModal
          proposal={selectedProposalForDetails}
          onClose={() => setSelectedProposalForDetails(null)}
          onOpenAudit={(cid) => setSelectedAuditCid(cid)}
        />
      )}

      {/* Footer */}
      </div>
    </div>
  );
};

export default App;
