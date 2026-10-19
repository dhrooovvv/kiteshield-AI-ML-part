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
  const roleDescriptions = { proposer: 'Create and submit payment proposals.', approver: 'Approve or reject escalated payments.', policyAdmin: 'Manage security policies and mandates.', demoAdmin: 'Combined access in isolated simulation only.' };
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
        ? 'This key belongs to another role. Select its matching role and retry.'
        : error instanceof KiteShieldAPIError && error.status === 401
        ? 'Key not accepted. Check the selected role and key.'
        : error instanceof KiteShieldAPIError && error.code === 'DEMO_ADMIN_SIMULATION_ONLY'
        ? 'Demo credentials work only in isolated simulation.'
        : 'Verification failed. Check the connection and retry. Your previous key is unchanged.');
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
              <h3 id="api-key-title" style={{ fontSize: '1.1rem', fontWeight: 600 }}>Connect API key</h3>
            </div>
            <p className="credential-intro">Choose a role and enter its application key.</p>
            <form onSubmit={handleSaveKey}>
              <label htmlFor="credential-role">Role</label>
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
              <p className="credential-role-hint">{roleDescriptions[credentialRole]}</p>
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
              <p className="credential-key-warning">Never enter a wallet private key or emergency-stop key.</p>
              <details className="credential-help"><summary>Connection details</summary>
                <p>Use the value of <code>{credentialNames[credentialRole]}</code> from <code>{credentialFile}</code>.</p>
                <p>Keys stay in memory until reload. Multiple roles can stay connected.</p>
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
