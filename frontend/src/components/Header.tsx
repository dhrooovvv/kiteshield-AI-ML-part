import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RefreshCw } from 'lucide-react';
import { api, credentialRoleLabels, KiteShieldAPIError } from '../api/client.ts';
import { useConnectedRoles } from '../useCredentials.ts';
import type { BackendHealth } from '../types/index.ts';
import type { CredentialRole } from '../api/client.ts';

interface HeaderProps {
  health: BackendHealth | null;
  title: string;
  onRefreshAll: () => void;
  loading: boolean;
}

export const Header: React.FC<HeaderProps> = ({ health, title, onRefreshAll, loading }) => {
  const connectedRoles = useConnectedRoles();
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [keyInput, setKeyInput] = useState(api.getApiKey());
  const [credentialRole, setCredentialRole] = useState<CredentialRole>('proposer');
  const [savingKey, setSavingKey] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const credentialNames = { proposer: 'API_KEY', approver: 'APPROVER_API_KEY', policyAdmin: 'POLICY_ADMIN_API_KEY', demoAdmin: 'DEMO_ADMIN_API_KEY' };
  const credentialFile = credentialRole === 'demoAdmin' ? 'backend/.env.demo' : 'backend/.env';
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
      await api.verifyAndSaveRoleKey(credentialRole, keyInput);
      setShowKeyModal(false);
      keyButton.current?.focus();
      onRefreshAll();
    } catch (error) {
      setKeyError(error instanceof KiteShieldAPIError && error.code === 'CREDENTIAL_ROLE_MISMATCH'
        ? 'This key belongs to a different role. Select its matching role; the previous credential was not replaced.'
        : error instanceof KiteShieldAPIError && error.status === 401
        ? `Key not accepted. Use the value of ${credentialNames[credentialRole]} from ${credentialFile}, without the variable name or surrounding quotes.`
        : error instanceof KiteShieldAPIError && error.code === 'DEMO_ADMIN_SIMULATION_ONLY'
        ? 'Demo administrator is disabled here. Start the isolated .env.demo simulation profile; this credential never grants live Sepolia access.'
        : 'Could not verify this credential. Check that the backend is running, then retry. No saved key was replaced.');
    } finally {
      setSavingKey(false);
    }
  };

  return (
    <header className="workspace-header">
      <h1>{title}</h1>
      <div className="workspace-controls">
        <span className={`execution-mode${verifiedLive ? ' execution-mode-live' : ''}`} role="status"
          title={verifiedLive ? `RPC verified at startup (${health?.rpc_verified_at ?? 'time unavailable'}); block is the latest observed at startup.` : undefined}>
          {!health ? 'Execution mode unavailable' : verifiedLive ? `Sepolia · chain 11155111 · block ${health.verified_block_number}` : health.execution_mode === 'simulated' ? 'Simulation · no on-chain broadcast' : 'Execution mode unverified'}
        </span>
        {!health && <span className="connection-warning" role="status">Connection unavailable</span>}
        <button className="btn btn-outline" onClick={onRefreshAll} disabled={loading} aria-label="Refresh data">
          <RefreshCw size={15} aria-hidden="true" />
          <span>{loading ? 'Refreshing…' : 'Refresh'}</span>
        </button>
        <div className="credential-controls" aria-label="Connected credentials">
        <button
          ref={keyButton}
          className="btn btn-outline"
          onClick={() => { setKeyError(null); setKeyInput(api.getRoleKey(credentialRole)); setShowKeyModal(true); }}
        >
          API key
        </button>
        <div className="credential-status" role="status" aria-live="polite">
          <span>{connectedRoles.length ? 'Connected roles' : 'Not authenticated'}</span>
          {connectedRoles.length > 0 && <strong>{connectedRoles.map(role => credentialRoleLabels[role]).join(' · ')}</strong>}
        </div>
        <button className="btn btn-outline"
          onClick={() => { setKeyError(null); setKeyInput(api.getRoleKey(credentialRole)); setShowKeyModal(true); }}>
          Switch role
        </button>
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
              <h3 id="api-key-title" style={{ fontSize: '1.1rem', fontWeight: 600 }}>API Authentication</h3>
            </div>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Multiple roles can stay connected and view data. Proposer creates, evaluates, and submits proposals; Human approver approves or rejects; Policy administrator changes policies. Keys and verified roles stay in memory until reload. Never enter a private signing key or emergency-stop key.
              {' '}Demo administrator combines these permissions only in the separate simulation database, never live Sepolia.
            </p>
            <form onSubmit={handleSaveKey}>
              <label htmlFor="credential-role">Credential role</label>
              <select id="credential-role" value={credentialRole} disabled={savingKey} style={{ width: '100%', marginBottom: '12px', padding: '10px' }}
                onChange={(event) => {
                  const role = event.target.value as typeof credentialRole;
                  setCredentialRole(role);
                  setKeyError(null);
                  setKeyInput(api.getRoleKey(role));
                }}>
                <option value="proposer">Proposer</option>
                <option value="approver">Human approver</option>
                <option value="policyAdmin">Policy administrator</option>
                <option value="demoAdmin">Demo administrator (simulation only)</option>
              </select>
              <p style={{ marginBottom: '10px', fontSize: '.85rem', color: 'var(--text-muted)' }}>
                Use {credentialNames[credentialRole]} from {credentialFile}. The backend must verify this exact role before it is connected.
              </p>
              <input
                type="password"
                aria-label="Application API key"
                autoComplete="off"
                autoFocus
                disabled={savingKey}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="Enter API Key"
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  background: 'var(--bg-input)',
                  border: '1px solid var(--border-light)',
                  color: 'var(--text-main)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.85rem',
                  marginBottom: '20px',
                }}
              />
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
                  {savingKey ? 'Verifying…' : credentialRole === 'proposer' ? 'Verify & connect' : 'Verify & save'}
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
