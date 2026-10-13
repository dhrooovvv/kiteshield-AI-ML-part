import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, Search, RefreshCw, CheckCircle2 } from 'lucide-react';
import { api } from '../api/client.ts';
import type { AuditIntegrityVerification, AuditTrail } from '../types/index.ts';

export const AuditView: React.FC = () => {
  const [correlationIdInput, setCorrelationIdInput] = useState('demo-prop-1');
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [trailLoading, setTrailLoading] = useState(false);
  const [trailError, setTrailError] = useState<string | null>(null);

  const [verification, setVerification] = useState<AuditIntegrityVerification | null>(null);
  const [verifying, setVerifying] = useState(false);

  const handleLookup = async (idToLookup?: string) => {
    const cid = (idToLookup || correlationIdInput).trim();
    if (!cid) return;

    setTrailLoading(true);
    setTrailError(null);
    try {
      const data = await api.getAuditTrail(cid);
      setTrail(data);
    } catch (err: unknown) {
      setTrailError(err instanceof Error ? err.message : 'Lookup failed');
      setTrail(null);
    } finally {
      setTrailLoading(false);
    }
  };

  const handleRunVerification = async () => {
    setVerifying(true);
    try {
      const res = await api.verifyAuditIntegrity(200);
      setVerification(res);
    } catch {
      // Ignored
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Cryptographic Audit Explorer</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Every lifecycle event is linked via SHA-256 hash chains. Private keys and secrets are strictly excluded.
        </p>
      </div>

      {/* Global Chain Verification Card */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                background: 'rgba(0, 242, 254, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid rgba(0, 242, 254, 0.3)',
              }}
            >
              <ShieldCheck size={22} color="var(--color-cyan)" />
            </div>
            <div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Global Hash Chain Integrity</h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Recomputes canonical SHA-256 hashes across recent database records to verify zero tampering
              </p>
            </div>
          </div>

          <button
            className="btn btn-primary"
            onClick={handleRunVerification}
            disabled={verifying}
          >
            <RefreshCw size={15} style={{ animation: verifying ? 'spin 1s linear infinite' : 'none' }} />
            <span>{verifying ? 'Verifying Chain...' : 'Verify Entire Hash Chain'}</span>
          </button>
        </div>

        {verification && (
          <div
            style={{
              marginTop: '16px',
              padding: '14px',
              borderRadius: '8px',
              background: verification.is_valid ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
              border: `1px solid ${verification.is_valid ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '10px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {verification.is_valid ? (
                <CheckCircle2 size={18} color="var(--color-emerald)" />
              ) : (
                <ShieldAlert size={18} color="var(--color-rose)" />
              )}
              <span style={{ fontSize: '0.9rem', fontWeight: 600, color: verification.is_valid ? '#34d399' : '#fb7185' }}>
                {verification.is_valid
                  ? 'Verification PASSED: 100% of checked audit records match cryptographic hash chain.'
                  : 'Verification FAILED: Inconsistency or missing link detected.'}
              </span>
            </div>

            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
              Checked {verification.checked_limit} most recent events
            </span>
          </div>
        )}
      </div>

      {/* Correlation ID Lookup */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '12px' }}>
          Inspect Lifecycle Events by Correlation ID
        </h3>

        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <input
              type="text"
              value={correlationIdInput}
              onChange={(e) => setCorrelationIdInput(e.target.value)}
              placeholder="Enter correlation ID (e.g. demo-prop-1)..."
              className="font-mono"
              style={{
                width: '100%',
                padding: '10px 14px',
                paddingLeft: '36px',
                borderRadius: '8px',
                background: 'var(--bg-input)',
                border: '1px solid var(--border-light)',
                color: '#fff',
                fontSize: '0.85rem',
              }}
            />
            <Search size={16} color="var(--text-dim)" style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} />
          </div>

          <button className="btn btn-outline" onClick={() => handleLookup()} disabled={trailLoading}>
            {trailLoading ? 'Searching...' : 'Lookup Trail'}
          </button>
        </div>

        {/* Trail Result */}
        {trailError && (
          <div style={{ padding: '12px', borderRadius: '6px', background: 'rgba(244, 63, 94, 0.1)', color: '#fb7185', fontSize: '0.85rem' }}>
            {trailError}
          </div>
        )}

        {trail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
              <span>Found {trail.events.length} chronological events</span>
              <span style={{ color: trail.chain_valid ? 'var(--color-emerald)' : 'var(--color-rose)', fontWeight: 600 }}>
                {trail.chain_valid ? 'Chain Verified Valid' : 'Chain Broken'}
              </span>
            </div>

            {trail.events.map((ev, i) => (
              <div
                key={ev.id}
                style={{
                  background: 'var(--bg-subtle)',
                  border: '1px solid var(--border-light)',
                  borderRadius: '8px',
                  padding: '14px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="badge badge-purple" style={{ fontSize: '0.72rem' }}>
                      #{i + 1} &bull; {ev.event_type}
                    </span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      Actor: <strong style={{ color: '#fff' }}>{ev.actor}</strong>
                    </span>
                  </div>

                  <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                    {new Date(ev.created_at).toLocaleString()}
                  </span>
                </div>

                <div className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--text-dim)', margin: '6px 0' }}>
                  Hash: <span style={{ color: 'var(--color-cyan)' }}>{ev.event_hash}</span>
                </div>

                <pre
                  className="font-mono"
                  style={{
                    background: 'rgba(0, 0, 0, 0.25)',
                    padding: '8px',
                    borderRadius: '6px',
                    color: '#94a3b8',
                    fontSize: '0.75rem',
                    overflowX: 'auto',
                  }}
                >
                  {JSON.stringify(ev.details, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
