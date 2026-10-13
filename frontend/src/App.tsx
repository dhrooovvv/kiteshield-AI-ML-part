import React, { useEffect, useState, useCallback } from 'react';
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
import { api } from './api/client.ts';
import type { BackendHealth, PendingApproval, Policy, Proposal } from './types/index.ts';

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<NavTab>('overview');
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [activePolicy, setActivePolicy] = useState<Policy | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // Modal states
  const [selectedApproval, setSelectedApproval] = useState<PendingApproval | null>(null);
  const [selectedAuditCid, setSelectedAuditCid] = useState<string | null>(null);
  const [selectedProposalForDetails, setSelectedProposalForDetails] = useState<Proposal | null>(null);

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    setGlobalError(null);

    try {
      // 1. Health
      try {
        const h = await api.checkHealth();
        setHealth(h);
      } catch {
        setHealth(null);
      }

      // 2. Active Policy
      try {
        const pol = await api.getActivePolicy();
        setActivePolicy(pol);
      } catch {
        setActivePolicy(null);
      }

      // 3. Proposals
      try {
        const propRes = await api.listProposals(undefined, 50, 0);
        setProposals(propRes.proposals);
      } catch (err: unknown) {
        console.warn('Failed to load proposals', err);
      }

      // 4. Pending Approvals
      try {
        const apps = await api.listPendingApprovals();
        setPendingApprovals(apps);
      } catch (err: unknown) {
        console.warn('Failed to load pending approvals', err);
      }
    } catch (err: unknown) {
      setGlobalError(err instanceof Error ? err.message : 'Error fetching backend state');
    } finally {
      setLoading(false);
    }
  }, []);

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

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top Header */}
      <Header health={health} onRefreshAll={fetchAllData} loading={loading} />

      {/* Main Navigation */}
      <Navigation
        currentTab={currentTab}
        onTabChange={setCurrentTab}
        pendingApprovalsCount={pendingApprovals.length}
        totalProposalsCount={proposals.length}
      />

      {/* Global error banner if backend is unreachable */}
      {globalError && (
        <div
          style={{
            maxWidth: '1440px',
            margin: '16px auto 0',
            width: 'calc(100% - 48px)',
            background: 'rgba(244, 63, 94, 0.15)',
            border: '1px solid rgba(244, 63, 94, 0.4)',
            color: '#fb7185',
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
      <main style={{ maxWidth: '1440px', width: '100%', margin: '0 auto', padding: '28px 24px', flex: 1 }}>
        {currentTab === 'overview' && (
          <OverviewView
            proposals={proposals}
            activePolicy={activePolicy}
            pendingApprovals={pendingApprovals}
            onProposalCreated={handleProposalCreated}
            onProposalUpdated={handleProposalUpdated}
            onPolicyUpdated={handlePolicyUpdated}
            onOpenAudit={(cid) => setSelectedAuditCid(cid)}
            onOpenDetails={(p) => setSelectedProposalForDetails(p)}
            onSelectApproval={(a) => setSelectedApproval(a)}
            onNavigateToTab={(t) => setCurrentTab(t)}
          />
        )}

        {currentTab === 'proposals' && (
          <ProposalsView
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
            onSelectApproval={(a) => setSelectedApproval(a)}
          />
        )}

        {currentTab === 'policies' && (
          <PoliciesView
            activePolicy={activePolicy}
            onPolicyUpdated={handlePolicyUpdated}
          />
        )}

        {currentTab === 'audit' && <AuditView />}
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
      <footer
        style={{
          borderTop: '1px solid var(--border-light)',
          padding: '16px 24px',
          textAlign: 'center',
          fontSize: '0.8rem',
          color: 'var(--text-dim)',
          background: 'rgba(8, 12, 20, 0.6)',
        }}
      >
        KiteShield Wallet &bull; Constrained AI Agent Authorization &bull; Sepolia Testnet &bull; Competition MVP
      </footer>
    </div>
  );
};

export default App;
