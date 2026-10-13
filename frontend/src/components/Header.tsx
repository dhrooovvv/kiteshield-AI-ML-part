import React, { useState } from 'react';
import { Shield, Key, RefreshCw } from 'lucide-react';
import { api } from '../api/client.ts';
import type { BackendHealth } from '../types/index.ts';

interface HeaderProps {
  health: BackendHealth | null;
  onRefreshAll: () => void;
  loading: boolean;
}

export const Header: React.FC<HeaderProps> = ({ health, onRefreshAll, loading }) => {
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [keyInput, setKeyInput] = useState(api.getApiKey());

  const handleSaveKey = (e: React.FormEvent) => {
    e.preventDefault();
    api.setApiKey(keyInput);
    setShowKeyModal(false);
    onRefreshAll();
  };

  return (
    <header
      style={{
        borderBottom: '1px solid var(--border-light)',
        padding: '16px 24px',
        background: 'rgba(8, 12, 20, 0.95)',
        backdropFilter: 'blur(12px)',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      <div
        style={{
          maxWidth: '1440px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '42px',
              height: '42px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, #00f2fe 0%, #4facfe 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: 'var(--glow-cyan)',
            }}
          >
            <Shield size={24} color="#040915" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '1.25rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                KiteShield Wallet
              </h1>
              <span
                style={{
                  fontSize: '0.65rem',
                  fontWeight: 700,
                  background: 'rgba(0, 242, 254, 0.15)',
                  color: 'var(--color-cyan)',
                  padding: '2px 8px',
                  borderRadius: '12px',
                  border: '1px solid rgba(0, 242, 254, 0.3)',
                }}
              >
                TESTNET MVP
              </span>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Give the agent hands, not the keys &bull; Sepolia (11155111)
            </p>
          </div>
        </div>

        {/* Status Badges & Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          {/* Health indicator */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              background: health ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
              border: `1px solid ${health ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
              fontSize: '0.8rem',
            }}
          >
            <span
              className="pulse-indicator"
              style={{ background: health ? 'var(--color-emerald)' : 'var(--color-rose)' }}
            />
            <span style={{ color: health ? '#34d399' : '#fb7185', fontWeight: 600 }}>
              {health ? 'Backend Healthy' : 'Disconnected'}
            </span>
          </div>

          {/* Signer address pill */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border-light)',
              fontSize: '0.8rem',
              color: 'var(--text-muted)',
            }}
            title="Isolated Signer Key (Testnet Sepolia only)"
          >
            <Shield size={14} color="var(--color-cyan)" />
            <span className="font-mono" style={{ color: 'var(--text-main)', fontSize: '0.78rem' }}>
              0x25a4...3e09
            </span>
          </div>

          {/* Refresh button */}
          <button
            className="btn btn-outline"
            style={{ padding: '8px 12px' }}
            onClick={onRefreshAll}
            disabled={loading}
            title="Refresh All Data"
          >
            <RefreshCw size={15} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>

          {/* API Key Modal Button */}
          <button
            className="btn btn-outline"
            style={{ padding: '8px 12px' }}
            onClick={() => setShowKeyModal(true)}
            title="Configure API Key"
          >
            <Key size={15} />
            <span style={{ fontSize: '0.8rem' }}>API Key</span>
          </button>
        </div>
      </div>

      {/* Key Modal */}
      {showKeyModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '16px',
          }}
        >
          <div className="glass-panel" style={{ width: '100%', maxWidth: '480px', padding: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <Key size={20} color="var(--color-cyan)" />
              <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>API Authentication</h3>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Enter the backend <code className="font-mono">X-API-Key</code>. Saved in your browser session for direct API communication.
            </p>
            <form onSubmit={handleSaveKey}>
              <input
                type="text"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="Enter API Key"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-light)',
                  color: '#fff',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.85rem',
                  marginBottom: '20px',
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => setShowKeyModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Key
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </header>
  );
};
