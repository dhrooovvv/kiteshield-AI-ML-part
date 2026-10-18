import React, { useState } from 'react';
import { Plus, Search } from 'lucide-react';
import { ProposalCard } from '../components/ProposalCard.tsx';
import { DirectProposalForm } from '../components/DirectProposalForm.tsx';
import { ProposalStatusFilter } from '../components/ProposalStatusFilter.tsx';
import { matchesProposalFilter } from '../proposalFilters.ts';
import type { ProposalFilter } from '../proposalFilters.ts';
import { useRole } from '../useCredentials.ts';
import type { Proposal } from '../types/index.ts';

interface ProposalsViewProps {
  proposals: Proposal[];
  onProposalCreated: (proposal: Proposal) => void;
  onProposalUpdated: (proposal: Proposal) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
  executionMode?: 'simulated' | 'sepolia';
}

export const ProposalsView: React.FC<ProposalsViewProps> = ({
  proposals,
  onProposalCreated,
  onProposalUpdated,
  onOpenAudit,
  onOpenDetails,
  executionMode,
}) => {
  const hasRequiredRole = useRole('proposer');
  const [filterStatus, setFilterStatus] = useState<ProposalFilter>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [showDirectForm, setShowDirectForm] = useState(false);

  const filtered = proposals.filter((p) => {
    if (!matchesProposalFilter(p.status, filterStatus)) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const matchPrompt = p.prompt.toLowerCase().includes(q);
      const matchRecipient = p.recipient.toLowerCase().includes(q);
      const matchId = p.id.toLowerCase().includes(q);
      if (!matchPrompt && !matchRecipient && !matchId) return false;
    }
    return true;
  });

  const hasFilters = filterStatus !== 'ALL' || searchQuery.trim() !== '';

  return (
    <section className="proposals-page" aria-label="Transaction proposals">
      <div className="proposals-page-heading">
        <div>
          <h2>Transaction proposals</h2>
          <p>Review transactions, check policy decisions, and track submission.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowDirectForm(!showDirectForm)}
          disabled={!hasRequiredRole && !showDirectForm} aria-expanded={showDirectForm} aria-controls="direct-proposal-form">
          <Plus size={16} aria-hidden="true" />
          {showDirectForm ? 'Close form' : 'New structured proposal'}
        </button>
      </div>

      {!hasRequiredRole && <p className="required-role-note proposals-role-note">Creating, evaluating, and submitting proposals requires Proposer. Connect it using Switch role.</p>}
      {showDirectForm && (
        <div id="direct-proposal-form" className="glass-panel proposals-direct-form">
          <h3>Submit a structured proposal</h3>
          <DirectProposalForm
            onProposalCreated={(created) => {
              onProposalCreated(created);
              setShowDirectForm(false);
            }}
            onCancel={() => setShowDirectForm(false)}
          />
        </div>
      )}

      <div className="proposals-toolbar">
        <label className="proposals-search">
          <Search size={17} aria-hidden="true" />
          <input type="search" value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search proposals" placeholder="Search prompt, recipient, or ID" />
        </label>
        <ProposalStatusFilter value={filterStatus} onChange={setFilterStatus} />
        <span className="proposals-result-count" role="status">
          {hasFilters ? `${filtered.length} of ${proposals.length}` : proposals.length} {filtered.length === 1 ? 'proposal' : 'proposals'}
        </span>
      </div>

      <div className="proposals-list">
        {filtered.length === 0 ? (
          <div className="glass-panel proposals-empty">
            <h3>{hasFilters ? 'No matching proposals' : 'No proposals yet'}</h3>
            <p>{hasFilters ? 'Try another search or status filter.' : 'Create a proposal to begin tracking transactions here.'}</p>
            {hasFilters && (
              <button className="btn btn-outline" onClick={() => { setSearchQuery(''); setFilterStatus('ALL'); }}>
                Clear filters
              </button>
            )}
          </div>
        ) : filtered.map((proposal) => (
          <ProposalCard key={proposal.id} proposal={proposal}
            executionMode={executionMode}
            onUpdated={onProposalUpdated} onOpenAudit={onOpenAudit} onOpenDetails={onOpenDetails} />
        ))}
      </div>
    </section>
  );
};
