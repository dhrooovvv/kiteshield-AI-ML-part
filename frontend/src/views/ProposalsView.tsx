import React, { useState } from 'react';
import { Filter, Plus, Search } from 'lucide-react';
import { ProposalCard } from '../components/ProposalCard.tsx';
import { DirectProposalForm } from '../components/DirectProposalForm.tsx';
import type { Proposal } from '../types/index.ts';

interface ProposalsViewProps {
  proposals: Proposal[];
  onProposalCreated: (proposal: Proposal) => void;
  onProposalUpdated: (proposal: Proposal) => void;
  onOpenAudit: (correlationId: string) => void;
  onOpenDetails: (proposal: Proposal) => void;
}

export const ProposalsView: React.FC<ProposalsViewProps> = ({
  proposals,
  onProposalCreated,
  onProposalUpdated,
  onOpenAudit,
  onOpenDetails,
}) => {
  const [filterStatus, setFilterStatus] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [showDirectForm, setShowDirectForm] = useState(false);

  const statusOptions = ['ALL', 'PROPOSED', 'ALLOWED', 'ESCALATED', 'BLOCKED', 'APPROVED', 'SUBMITTED'];

  const filtered = proposals.filter((p) => {
    if (filterStatus !== 'ALL' && p.status !== filterStatus) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchPrompt = p.prompt.toLowerCase().includes(q);
      const matchRecipient = p.recipient.toLowerCase().includes(q);
      const matchId = p.id.toLowerCase().includes(q);
      if (!matchPrompt && !matchRecipient && !matchId) return false;
    }
    return true;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Title & Actions Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Transaction Proposals</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Full lifecycle tracking: Prompt &rarr; Normalization &rarr; Policy Evaluation &rarr; Signing &rarr; Broadcast
          </p>
        </div>

        <button
          className="btn btn-primary"
          onClick={() => setShowDirectForm(!showDirectForm)}
        >
          <Plus size={16} />
          <span>{showDirectForm ? 'Close Form' : 'New Structured Proposal'}</span>
        </button>
      </div>

      {/* Collapsible Manual Proposal Form */}
      {showDirectForm && (
        <div className="glass-panel" style={{ padding: '24px' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '14px' }}>
            Submit Direct Proposal
          </h3>
          <DirectProposalForm
            onProposalCreated={(created) => {
              onProposalCreated(created);
              setShowDirectForm(false);
            }}
            onCancel={() => setShowDirectForm(false)}
          />
        </div>
      )}

      {/* Filter and Search Bar */}
      <div
        className="glass-panel"
        style={{
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        {/* Search */}
        <div style={{ position: 'relative', width: '280px' }}>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search prompt, recipient, ID..."
            style={{
              width: '100%',
              padding: '8px 12px',
              paddingLeft: '34px',
              borderRadius: '8px',
              background: 'var(--bg-input)',
              border: '1px solid var(--border-light)',
              color: '#fff',
              fontSize: '0.85rem',
            }}
          />
          <Search size={15} color="var(--text-dim)" style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }} />
        </div>

        {/* Status Pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflowX: 'auto' }}>
          <Filter size={15} color="var(--text-dim)" style={{ marginRight: '4px' }} />
          {statusOptions.map((st) => (
            <button
              key={st}
              onClick={() => setFilterStatus(st)}
              style={{
                background: filterStatus === st ? 'rgba(0, 242, 254, 0.2)' : 'var(--bg-subtle)',
                color: filterStatus === st ? 'var(--color-cyan)' : 'var(--text-muted)',
                border: `1px solid ${filterStatus === st ? 'var(--color-cyan)' : 'var(--border-light)'}`,
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'var(--font-main)',
              }}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Proposal Cards List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {filtered.length === 0 ? (
          <div className="glass-panel" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-dim)' }}>
            No proposals match the current filter or search criteria.
          </div>
        ) : (
          filtered.map((proposal) => (
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
  );
};
