import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ShieldAlert, Edit2, Copy, Check, ExternalLink } from 'lucide-react';
import { ethToWei, weiToEth } from '../amounts.ts';
import { api } from '../api/client.ts';
import { useRole } from '../useCredentials.ts';
import type { Policy } from '../types/index.ts';

interface PolicyCardProps {
  policy: Policy | null;
  onPolicyUpdated: (updated: Policy) => void;
}

export const PolicyCard: React.FC<PolicyCardProps> = ({ policy, onPolicyUpdated }) => {
  const hasRequiredRole = useRole('policyAdmin');
  const [showEditor, setShowEditor] = useState(false);
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const [maxEth, setMaxEth] = useState(
    policy ? weiToEth(policy.max_amount_wei) : '1.0'
  );
  const [escalateEth, setEscalateEth] = useState(
    policy?.escalation_threshold_wei ? weiToEth(policy.escalation_threshold_wei) : '0.1'
  );
  const [dailyEth, setDailyEth] = useState(
    policy?.daily_limit_wei ? weiToEth(policy.daily_limit_wei) : '5.0'
  );
  const [allowedInput, setAllowedInput] = useState(
    policy?.allowed_recipients ? policy.allowed_recipients.join('\n') : ''
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const fieldId = useId();

  useEffect(() => {
    if (showEditor) dialogRef.current?.showModal();
  }, [showEditor]);

  const closeEditor = () => {
    if (loading) return;
    setShowEditor(false);
    triggerRef.current?.focus();
  };

  const openEditor = () => {
    setMaxEth(policy ? weiToEth(policy.max_amount_wei) : '1.0');
    setEscalateEth(policy ? (policy.escalation_threshold_wei === null ? '' : weiToEth(policy.escalation_threshold_wei)) : '0.1');
    setDailyEth(policy ? (policy.daily_limit_wei === null ? '' : weiToEth(policy.daily_limit_wei)) : '5.0');
    setAllowedInput(policy?.allowed_recipients?.join('\n') || '');
    setError(null);
    setShowEditor(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hasRequiredRole) { setError('Policy administrator credential required. Connect it using Switch role.'); return; }
    setLoading(true);
    setError(null);

    try {
      const maxWei = ethToWei(maxEth);
      const escWei = escalateEth ? ethToWei(escalateEth) : null;
      const dailyWei = dailyEth ? ethToWei(dailyEth) : null;

      const allowedList = allowedInput
        .split('\n')
        .map((s) => s.trim())
        .filter((s) => s.length > 0);

      const newPolicy = await api.createPolicy({
        max_amount_wei: maxWei,
        escalation_threshold_wei: escWei,
        daily_limit_wei: dailyWei,
        allowed_recipients: allowedList.length > 0 ? allowedList : null,
      });

      onPolicyUpdated(newPolicy);
      setShowEditor(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update policy');
    } finally {
      setLoading(false);
    }
  };

  const editor = showEditor && createPortal(
    <dialog ref={dialogRef} className="policy-editor-dialog" aria-labelledby={fieldId + '-title'}
      onCancel={(event) => { event.preventDefault(); closeEditor(); }}>
      <form onSubmit={handleSave} aria-busy={loading}>
        <div className="policy-editor-header">
          <h2 id={fieldId + '-title'}>{policy ? 'Update security policy' : 'Create security policy'}</h2>
          <p>{policy ? `Publishing creates version ${policy.version + 1} and makes it the active policy.` : 'Set spending limits and recipient restrictions for transaction evaluation.'}</p>
        </div>
        <fieldset className="policy-editor-fields" disabled={loading || !hasRequiredRole}>
          <legend>Spending limits</legend>
          <div className="policy-editor-field">
            <label htmlFor={fieldId + '-maximum'}>Maximum transaction amount <span>ETH</span></label>
            <input id={fieldId + '-maximum'} type="text" inputMode="decimal" required autoFocus
              value={maxEth} onChange={(event) => setMaxEth(event.target.value)} />
          </div>
          <div className="policy-editor-field">
            <label htmlFor={fieldId + '-approval'}>Human approval threshold <span>ETH · Optional</span></label>
            <input id={fieldId + '-approval'} type="text" inputMode="decimal"
              aria-describedby={fieldId + '-approval-help'} value={escalateEth}
              onChange={(event) => setEscalateEth(event.target.value)} />
            <p id={fieldId + '-approval-help'}>Amounts at or above this threshold require human approval. Leave blank to disable this threshold.</p>
          </div>
          <div className="policy-editor-field">
            <label htmlFor={fieldId + '-daily'}>Daily spending budget <span>ETH · Optional</span></label>
            <input id={fieldId + '-daily'} type="text" inputMode="decimal"
              aria-describedby={fieldId + '-daily-help'} value={dailyEth}
              onChange={(event) => setDailyEth(event.target.value)} />
            <p id={fieldId + '-daily-help'}>Leave blank for no daily budget limit.</p>
          </div>
        </fieldset>
        <fieldset className="policy-editor-fields policy-editor-recipients" disabled={loading || !hasRequiredRole}>
          <legend>Recipient restrictions</legend>
          <div className="policy-editor-field">
            <label htmlFor={fieldId + '-recipients'}>Allowed recipients</label>
            <textarea id={fieldId + '-recipients'} rows={3} className="font-mono"
              aria-describedby={fieldId + '-recipients-help'} value={allowedInput}
              onChange={(event) => setAllowedInput(event.target.value)} />
            <p id={fieldId + '-recipients-help'}>Enter one wallet address per line. An empty list allows any recipient, subject to the remaining policy checks.</p>
          </div>
        </fieldset>
        {error && <p className="policy-editor-error" role="alert">{error}</p>}
        <div className="policy-editor-actions">
          <button type="button" className="btn btn-outline" onClick={closeEditor} disabled={loading}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={loading || !hasRequiredRole}>
            {loading ? 'Publishing…' : policy ? `Publish version ${policy.version + 1}` : 'Create policy'}
          </button>
        </div>
      </form>
    </dialog>, document.body
  );

  if (!policy) {
    return (
      <>
        <div className="glass-panel policy-panel" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          <ShieldAlert size={32} color="var(--color-amber)" style={{ marginBottom: '10px' }} />
          <p>No active security policy found in system.</p>
          <p className="required-role-note">{hasRequiredRole ? 'Policy-edit permission verified.' : 'Requires Policy administrator, or Demo administrator in simulation. Connect it using Switch role.'}</p>
          <button className="btn btn-primary" style={{ marginTop: '14px' }} ref={triggerRef} onClick={openEditor} disabled={!hasRequiredRole}>
            Create Initial Policy
          </button>
        </div>

        {editor}
      </>
    );
  }

  const maxAmountEth = weiToEth(policy.max_amount_wei);
  const threshold = policy.escalation_threshold_wei
    ? weiToEth(policy.escalation_threshold_wei) : null;
  const limits = [
    { label: 'Autonomous cap', value: threshold ? `< ${threshold} ETH` : `≤ ${maxAmountEth} ETH` },
    { label: 'Escalation threshold', value: threshold ? `≥ ${threshold} ETH` : 'None' },
    { label: 'Absolute max cap', value: `${maxAmountEth} ETH` },
    { label: 'Daily budget', value: policy.daily_limit_wei ? `${weiToEth(policy.daily_limit_wei)} ETH` : 'Unlimited',
      help: 'UTC calendar day; gas excluded; pending reservations remain held.' },
  ];

  const copyAddress = async (address: string) => {
    try {
      await navigator.clipboard.writeText(address);
      setCopiedAddress(address);
      setCopyError(false);
    } catch {
      setCopyError(true);
      setCopiedAddress(null);
    }
  };

  return (
    <div className="glass-panel policy-panel">
      <div className="policy-panel-heading">
        <div>
          <h3>Active Security Policy</h3>
          <span className="badge badge-allow">Version {policy.version}</span>
        </div>
        <button className="btn btn-outline" ref={triggerRef} onClick={openEditor}
          disabled={!hasRequiredRole}
          aria-label="Update Rules"
          title={hasRequiredRole ? 'Publish a new policy version' : 'Requires Policy administrator. Connect using Switch role.'}>
          <Edit2 size={14} aria-hidden="true" /> Edit
        </button>
      </div>

      <dl className="policy-limits">
        {limits.map(limit => (
          <div key={limit.label} title={limit.help}>
            <dt>{limit.label}</dt>
            <dd>{limit.value}</dd>
          </div>
        ))}
      </dl>

      <div className="policy-allowlist">
        <h4>Recipient allowlist <span>{policy.allowed_recipients?.length || 0}</span></h4>
        {policy.allowed_recipients && policy.allowed_recipients.length > 0 ? (
          <ul className="policy-address-list">
            {policy.allowed_recipients.map(address => (
              <li key={address}>
                <span className="policy-address">{address}</span>
                <div className="policy-address-actions">
                  <button type="button" className="policy-address-action"
                    aria-label={`Copy address ${address}`} title="Copy address"
                    onClick={() => copyAddress(address)}>
                    {copiedAddress === address ? <Check size={15} /> : <Copy size={15} />}
                  </button>
                  <a className="policy-address-action" href={`https://sepolia.etherscan.io/address/${address}`}
                    target="_blank" rel="noopener noreferrer" title="View on Sepolia Etherscan"
                    aria-label={`View address ${address} on Sepolia Etherscan`}>
                    <ExternalLink size={15} />
                  </a>
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="policy-permissive">Any recipient allowed, subject to policy limits.</p>}
        {(copiedAddress || copyError) && <p className="policy-copy-feedback" role="status">
          {copyError ? 'Copy unavailable. Select the address to copy it.' : 'Address copied'}
        </p>}
      </div>
      {editor}
    </div>
  );
};
