import React, { useEffect, useState } from 'react';
import { History, ShieldCheck, ShieldAlert, X, Link as LinkIcon, RefreshCw } from 'lucide-react';
import { api } from '../api/client.ts';
import type { AuditTrail } from '../types/index.ts';

interface AuditTrailModalProps {
  correlationId: string;
  onClose: () => void;
}

export const AuditTrailModal: React.FC<AuditTrailModalProps> = ({
  correlationId,
  onClose,
}) => {
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    const fetchTrail = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getAuditTrail(correlationId);
        if (isMounted) setTrail(data);
      } catch (err: unknown) {
        if (isMounted) setError(err instanceof Error ? err.message : 'Failed to fetch audit trail');
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchTrail();
    return () => {
      isMounted = false;
    };
  }, [correlationId]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
      }}
    >
      <div
        className="glass-panel"
        style={{
          width: '100%',
          maxWidth: '720px',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          padding: '24px',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: '8px',
                background: 'rgba(0, 242, 254, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px solid rgba(0, 242, 254, 0.3)',
              }}
            >
              <History size={20} color="var(--color-cyan)" />
            </div>
            <div>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600 }}>Immutable Audit Chain</h3>
              <p className="font-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                Correlation ID: {correlationId}
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-dim)',
              cursor: 'pointer',
              padding: '4px',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Chain Integrity Badge */}
        {trail && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 14px',
              borderRadius: '8px',
              background: trail.chain_valid ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
              border: `1px solid ${trail.chain_valid ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
              marginBottom: '16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {trail.chain_valid ? (
                <ShieldCheck size={18} color="var(--color-emerald)" />
              ) : (
                <ShieldAlert size={18} color="var(--color-rose)" />
              )}
              <span
                style={{
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  color: trail.chain_valid ? '#34d399' : '#fb7185',
                }}
              >
                {trail.chain_valid
                  ? 'SHA-256 Hash Chain Intact (Tamper-Free)'
                  : 'Hash Chain Broken / Inconsistent'}
              </span>
            </div>

            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
              {trail.events.length} event{trail.events.length !== 1 ? 's' : ''} recorded
            </span>
          </div>
        )}

        {/* Events Scroll Area */}
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: '6px' }}>
          {loading && (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              <RefreshCw size={24} style={{ animation: 'spin 1s linear infinite', marginBottom: '8px' }} />
              <p>Verifying cryptographic audit chain...</p>
            </div>
          )}

          {error && (
            <div
              style={{
                padding: '16px',
                borderRadius: '8px',
                background: 'rgba(244, 63, 94, 0.1)',
                border: '1px solid rgba(244, 63, 94, 0.3)',
                color: '#fb7185',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}

          {trail && trail.events.length === 0 && !loading && (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-dim)' }}>
              No audit events found for this correlation ID.
            </div>
          )}

          {trail && trail.events.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', position: 'relative' }}>
              {trail.events.map((ev, idx) => (
                <div
                  key={ev.id}
                  style={{
                    background: 'var(--bg-subtle)',
                    border: '1px solid var(--border-light)',
                    borderRadius: '10px',
                    padding: '14px',
                    position: 'relative',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span className="badge badge-purple" style={{ fontSize: '0.72rem' }}>
                        #{idx + 1} &bull; {ev.event_type}
                      </span>
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>
                        by <strong style={{ color: 'var(--text-main)' }}>{ev.actor}</strong>
                      </span>
                    </div>

                    <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>
                      {new Date(ev.created_at).toLocaleTimeString()}
                    </span>
                  </div>

                  {/* Hashes */}
                  <div
                    style={{
                      background: 'rgba(0, 0, 0, 0.3)',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      marginBottom: '10px',
                      fontSize: '0.73rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-dim)', marginBottom: '3px' }}>
                      <LinkIcon size={11} />
                      <span>Prev Hash:</span>
                      <span className="font-mono" style={{ color: '#94a3b8' }}>
                        {ev.previous_hash ? ev.previous_hash.slice(0, 24) + '...' : 'GENESIS'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-dim)' }}>
                      <ShieldCheck size={11} color="var(--color-cyan)" />
                      <span>Event Hash:</span>
                      <span className="font-mono" style={{ color: 'var(--color-cyan)' }}>
                        {ev.event_hash.slice(0, 24)}...
                      </span>
                    </div>
                  </div>

                  {/* Details JSON */}
                  <div style={{ fontSize: '0.75rem' }}>
                    <span style={{ color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                      Event Details:
                    </span>
                    <pre
                      className="font-mono"
                      style={{
                        background: 'rgba(0, 0, 0, 0.2)',
                        padding: '8px',
                        borderRadius: '6px',
                        color: '#cbd5e1',
                        overflowX: 'auto',
                        maxHeight: '120px',
                      }}
                    >
                      {JSON.stringify(ev.details, null, 2)}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: '16px', marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
          <button className="btn btn-outline" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
