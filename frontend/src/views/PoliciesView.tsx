import React, { useEffect, useState } from 'react';
import { History, RefreshCw } from 'lucide-react';
import { PolicyCard } from '../components/PolicyCard.tsx';
import { weiToEth } from '../amounts.ts';
import { api } from '../api/client.ts';
import type { Policy } from '../types/index.ts';

interface PoliciesViewProps {
  activePolicy: Policy | null;
  onPolicyUpdated: (updated: Policy) => void;
  refreshRevision: number;
}

export const PoliciesView: React.FC<PoliciesViewProps> = ({
  activePolicy,
  onPolicyUpdated,
  refreshRevision,
}) => {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listPolicies();
      setPolicies(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unable to refresh policy history. Retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void fetchHistory();
    });
  }, [fetchHistory, activePolicy, refreshRevision]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Policy Engine & Governance</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Autonomous boundaries are immutably versioned. Stale capability tokens bound to prior deactivated versions fail validation.
        </p>
      </div>

      {/* Active Policy */}
      <PolicyCard policy={activePolicy} onPolicyUpdated={onPolicyUpdated} />

      {/* Version History */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <History size={18} color="var(--color-cyan)" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Immutable Version History</h3>
          </div>

          <button className="btn btn-outline" style={{ padding: '6px 12px', fontSize: '0.8rem' }} onClick={fetchHistory} disabled={loading}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            <span>Refresh History</span>
          </button>
        </div>

        {error && <p className="audit-error" role="alert">{error}</p>}
        {loading && <p role="status">Refreshing policy history…</p>}
        {!error && !loading && policies.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '24px' }}>
            No historical policy versions found.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {policies.map((p) => {
              const maxEth = weiToEth(p.max_amount_wei);
              const escEth = p.escalation_threshold_wei
                ? weiToEth(p.escalation_threshold_wei)
                : 'None';
              return (
                <div
                  key={p.id}
                  style={{
                    background: 'var(--bg-subtle)',
                    border: `1px solid ${p.is_active ? 'rgba(21, 154, 103, 0.35)' : 'var(--border-light)'}`,
                    borderRadius: '8px',
                    padding: '12px 16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span className="font-mono" style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-main)' }}>
                      Version {p.version}
                    </span>
                    {p.is_active && <span className="badge badge-allow">ACTIVE</span>}
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
                      Published {new Date(p.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '0.82rem' }}>
                    <div>
                      <span style={{ color: 'var(--text-dim)' }}>Autonomous Cap: </span>
                      <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>&le; {escEth} ETH</span>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-dim)' }}>Max Limit: </span>
                      <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{maxEth} ETH</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
