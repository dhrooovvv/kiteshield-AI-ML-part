import React, { useState } from 'react';
import { Send, AlertCircle } from 'lucide-react';
import { api } from '../api/client.ts';
import type { Proposal } from '../types/index.ts';

interface DirectProposalFormProps {
  onProposalCreated: (proposal: Proposal) => void;
  onCancel: () => void;
}

export const DirectProposalForm: React.FC<DirectProposalFormProps> = ({
  onProposalCreated,
  onCancel,
}) => {
  const [recipient, setRecipient] = useState('0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e');
  const [amountEth, setAmountEth] = useState('0.05');
  const [prompt, setPrompt] = useState('Direct manual proposal via dashboard');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const ethNum = parseFloat(amountEth);
      if (isNaN(ethNum) || ethNum <= 0) {
        throw new Error('Please enter a positive ETH amount');
      }
      const amountWei = BigInt(Math.round(ethNum * 1e18)).toString();

      const created = await api.createDirectProposal({
        prompt: prompt.trim() || 'Manual transfer proposal',
        recipient: recipient.trim(),
        amount_wei: amountWei,
        chain_id: 11155111,
      });

      onProposalCreated(created);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Proposal submission failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div>
        <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
          Destination Address (Sepolia):
        </label>
        <input
          type="text"
          value={recipient}
          onChange={(e) => setRecipient(e.target.value)}
          required
          placeholder="0x..."
          className="font-mono"
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'var(--bg-input)',
            border: '1px solid var(--border-light)',
            color: '#fff',
            fontSize: '0.85rem',
          }}
        />
      </div>

      <div>
        <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
          Transfer Amount (ETH):
        </label>
        <input
          type="number"
          step="any"
          min="0.000000000000000001"
          value={amountEth}
          onChange={(e) => setAmountEth(e.target.value)}
          required
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'var(--bg-input)',
            border: '1px solid var(--border-light)',
            color: '#fff',
            fontSize: '0.85rem',
          }}
        />
      </div>

      <div>
        <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '6px' }}>
          Action Description / Intent:
        </label>
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Protocol node grant payment"
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'var(--bg-input)',
            border: '1px solid var(--border-light)',
            color: '#fff',
            fontSize: '0.85rem',
          }}
        />
      </div>

      {error && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'rgba(244, 63, 94, 0.1)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: '#fb7185',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
        <button type="button" className="btn btn-outline" onClick={onCancel} disabled={loading}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          <Send size={15} />
          <span>{loading ? 'Submitting...' : 'Submit Proposal'}</span>
        </button>
      </div>
    </form>
  );
};
