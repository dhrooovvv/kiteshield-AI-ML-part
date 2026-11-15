import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RefreshCw, MessageSquare } from 'lucide-react';
import { api, credentialRoleLabels, KiteShieldAPIError } from '../api/client.ts';
import { useConnectedRoles } from '../useCredentials.ts';
import type { BackendHealth } from '../types/index.ts';

interface HeaderProps {
  health: BackendHealth | null;
  title: string;
  onRefreshAll: () => void;
  loading: boolean;
  onOpenAssistant?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ health, title, onRefreshAll, loading, onOpenAssistant }) => {
  const connectedRoles = useConnectedRoles();
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [keyInput, setKeyInput] = useState(api.getApiKey());
  const [savingKey, setSavingKey] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const keyDialog = useRef<HTMLDialogElement>(null);
  const keyButton = useRef<HTMLButtonElement>(null);
  const verifiedLive = health?.execution_mode === 'sepolia'
    && health.verified_chain_id === 11155111
    && typeof health.verified_block_number === 'number'
    && Number.isSafeInteger(health.verified_block_number)
    && health.verified_block_number >= 0;

  useEffect(() => {
    if (showKeyModal) keyDialog.current?.showModal();
  }, [showKeyModal]);

  const closeKeyDialog = () => {
    if (savingKey) return;
    setShowKeyModal(false);
    keyButton.current?.focus();
  };

  const handleSaveKey = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingKey(true);
    setKeyError(null);
    try {
      await api.connect(keyInput);
      setKeyInput('');
      setShowKeyModal(false);
      keyButton.current?.focus();
      onRefreshAll();
    } catch (error) {
      setKeyError(error instanceof KiteShieldAPIError && error.status === 401
        ? 'Key not accepted. Check your application key.'
        : error instanceof KiteShieldAPIError && error.code === 'DEMO_ADMIN_SIMULATION_ONLY'
        ? 'Demo credentials work only in isolated simulation.'
        : 'Verification failed. Check the connection and retry.');
    } finally {
      setSavingKey(false);
    }
  };

  return (
    <header className="workspace-header">
      <h1>{title}</h1>
      <div className="workspace-controls">
        {onOpenAssistant && <button className="btn btn-outline" onClick={onOpenAssistant}><MessageSquare size={15} /> Ask KiteShield</button>}
        <span className={`execution-mode${verifiedLive ? ' execution-mode-live' : ''}`} role="status"
          title={verifiedLive ? `RPC verified at startup (${health?.rpc_verified_at ?? 'time unavailable'}); block is the latest observed at startup.` : undefined}>
          {!health ? 'Execution mode unavailable' : verifiedLive ? `Sepolia · chain 11155111 · block ${health.verified_block_number}` : health.execution_mode === 'simulated' ? 'Simulation · no on-chain broadcast' : 'Execution mode unverified'}
        </span>
        {!health && <span className="connection-warning" role="status">Connection unavailable</span>}
        <button className="btn btn-outline" onClick={onRefreshAll} disabled={loading} aria-label="Refresh data">
          <RefreshCw size={15} aria-hidden="true" />
          <span>{loading ? 'Refreshing…' : 'Refresh'}</span>
        </button>
        <div className="credential-controls" aria-label="Admin connection">
          <div className="credential-status" role="status" aria-live="polite">
            <span>{connectedRoles.length ? 'Connected' : 'Disconnected'}</span>
            {connectedRoles.length > 0 && <strong>{connectedRoles.includes('admin') ? 'Admin' : credentialRoleLabels[connectedRoles[0]]}</strong>}
          </div>
          <button ref={keyButton} className="btn btn-outline" onClick={() => {
            if (connectedRoles.length) { api.disconnect(); setKeyInput(''); onRefreshAll(); }
            else { setKeyError(null); setKeyInput(''); setShowKeyModal(true); }
          }}>{connectedRoles.length ? 'Disconnect' : 'Connect'}</button>
        </div>
      </div>

      {/* Key Modal */}
      {showKeyModal && createPortal(
        <dialog
          ref={keyDialog}
          className="api-key-dialog"
          aria-labelledby="api-key-title"
          onCancel={(event) => { event.preventDefault(); closeKeyDialog(); }}
        >
          <div className="glass-panel" style={{ width: '100%', maxWidth: '480px', padding: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <h3 id="api-key-title" style={{ fontSize: '1.1rem', fontWeight: 600 }}>Connect to KiteShield</h3>
            </div>
            <p className="credential-intro">Enter your Admin application key.</p>
            <form onSubmit={handleSaveKey}>
              <label className="credential-key-label" htmlFor="application-api-key">API key</label>
              <input
                id="application-api-key"
                type="password"
                aria-label="Application API key"
                autoComplete="off"
                autoFocus
                disabled={savingKey}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="Paste application key"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-light)',
                  color: 'var(--text-main)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.85rem',
                  marginBottom: '8px',
                }}
              />
              <p className="credential-key-warning">Use your application key. Keep wallet keys private.</p>
              <details className="credential-help"><summary>Connection details</summary>
                <p>Use your configured Admin key. Access is verified by the server.</p>
                <p>The key stays in memory until disconnect or reload.</p>
              </details>
              {keyError && <p role="alert" style={{ color: '#a32e3c', marginBottom: '16px' }}>{keyError}</p>}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={closeKeyDialog}
                  disabled={savingKey}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={savingKey || !keyInput.trim()}>
                  {savingKey ? 'Verifying…' : 'Verify & connect'}
                </button>
              </div>
            </form>
          </div>
        </dialog>, document.body
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
