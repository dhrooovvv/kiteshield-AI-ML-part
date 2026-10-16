import React, { useState } from 'react';
import { ShieldCheck, CheckCircle, AlertTriangle, ShieldAlert, Edit2 } from 'lucide-react';
import { api } from '../api/client.ts';
import type { Policy } from '../types/index.ts';

interface PolicyCardProps {
  policy: Policy | null;
  onPolicyUpdated: (updated: Policy) => void;
}

export const PolicyCard: React.FC<PolicyCardProps> = ({ policy, onPolicyUpdated }) => {
  const [showEditor, setShowEditor] = useState(false);
  const [maxEth, setMaxEth] = useState(
    policy ? (Number(policy.max_amount_wei) / 1e18).toString() : '1.0'
  );
  const [escalateEth, setEscalateEth] = useState(
    policy?.escalation_threshold_wei ? (Number(policy.escalation_threshold_wei) / 1e18).toString() : '0.1'
  );
  const [dailyEth, setDailyEth] = useState(
    policy?.daily_limit_wei ? (Number(policy.daily_limit_wei) / 1e18).toString() : '5.0'
  );
  const [allowedInput, setAllowedInput] = useState(
    policy?.allowed_recipients ? policy.allowed_recipients.join('\n') : ''
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const maxWei = BigInt(Math.round(parseFloat(maxEth) * 1e18)).toString();
      const escWei = escalateEth ? BigInt(Math.round(parseFloat(escalateEth) * 1e18)).toString() : null;
      const dailyWei = dailyEth ? BigInt(Math.round(parseFloat(dailyEth) * 1e18)).toString() : null;

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

  if (!policy) {
    return (
      <>
        <div className="glass-panel" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
          <ShieldAlert size={32} color="var(--color-amber)" style={{ marginBottom: '10px' }} />
          <p>No active security policy found in system.</p>
          <button className="btn btn-primary" style={{ marginTop: '14px' }} onClick={() => setShowEditor(true)}>
            Create Initial Policy
          </button>
        </div>

        {showEditor && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0, 0, 0, 0.8)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
              padding: '16px',
            }}
          >
            <div className="glass-panel" style={{ width: '100%', maxWidth: '520px', padding: '24px' }}>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '6px' }}>
                Create Initial Security Policy
              </h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
                Configure the deterministic limits used before any transaction can be authorized.
              </p>

              <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                    Max Amount per Transaction (ETH):
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={maxEth}
                    onChange={(e) => setMaxEth(e.target.value)}
                    required
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-light)',
                      color: '#fff',
                    }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                    Human Escalation Threshold (ETH):
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={escalateEth}
                    onChange={(e) => setEscalateEth(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-light)',
                      color: '#fff',
                    }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                    Daily Spending Budget (ETH):
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    value={dailyEth}
                    onChange={(e) => setDailyEth(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-light)',
                      color: '#fff',
                    }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                    Allowed Recipients (one address per line):
                  </label>
                  <textarea
                    value={allowedInput}
                    onChange={(e) => setAllowedInput(e.target.value)}
                    rows={3}
                    className="font-mono"
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-light)',
                      color: '#fff',
                      fontSize: '0.78rem',
                    }}
                  />
                </div>

                {error && (
                  <div style={{ color: '#fb7185', fontSize: '0.82rem', padding: '8px', background: 'rgba(244, 63, 94, 0.1)', borderRadius: '6px' }}>
                    {error}
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                  <button type="button" className="btn btn-outline" onClick={() => setShowEditor(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={loading}>
                    {loading ? 'Creating...' : 'Create Policy'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </>
    );
  }

  const maxAmountEth = (Number(policy.max_amount_wei) / 1e18).toFixed(4).replace(/\.?0+$/, '');
  const escThresholdEth = policy.escalation_threshold_wei
    ? (Number(policy.escalation_threshold_wei) / 1e18).toFixed(4).replace(/\.?0+$/, '')
    : 'None';
  const dailyLimitEth = policy.daily_limit_wei
    ? (Number(policy.daily_limit_wei) / 1e18).toFixed(4).replace(/\.?0+$/, '')
    : 'Unlimited';

  return (
    <div className="glass-panel" style={{ padding: '24px' }}>
      {/* Title & Actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: 'rgba(16, 185, 129, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid rgba(16, 185, 129, 0.3)',
            }}
          >
            <ShieldCheck size={20} color="var(--color-emerald)" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Active Security Policy</h3>
              <span className="badge badge-allow" style={{ fontSize: '0.7rem' }}>
                Version {policy.version}
              </span>
            </div>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Deterministic bounds enforced by KiteShield PolicyEngine
            </p>
          </div>
        </div>

        <button className="btn btn-outline" onClick={() => setShowEditor(true)}>
          <Edit2 size={14} />
          <span>Update Rules</span>
        </button>
      </div>

      {/* Thresholds Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '14px',
          marginBottom: '20px',
        }}
      >
        <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', padding: '14px', borderRadius: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-emerald)', fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase' }}>
            <CheckCircle size={14} />
            <span>Autonomous Cap</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '6px' }}>
            &le; {escThresholdEth} ETH
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '2px' }}>
            Transfers under this amount are automatically allowed
          </div>
        </div>

        <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', padding: '14px', borderRadius: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-amber)', fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase' }}>
            <AlertTriangle size={14} />
            <span>Escalation Threshold</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '6px' }}>
            &gt; {escThresholdEth} ETH
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '2px' }}>
            Transfers above this require explicit human authorization
          </div>
        </div>

        <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', padding: '14px', borderRadius: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-rose)', fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase' }}>
            <ShieldAlert size={14} />
            <span>Absolute Max Cap</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '6px' }}>
            {maxAmountEth} ETH
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '2px' }}>
            Strict denial &mdash; no action above this can be signed
          </div>
        </div>

        <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', padding: '14px', borderRadius: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--color-blue)', fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase' }}>
            <ShieldCheck size={14} />
            <span>Daily Budget Limit</span>
          </div>
          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff', marginTop: '6px' }}>
            {dailyLimitEth} ETH
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '2px' }}>
            Rolling daily aggregate limit across all proposals
          </div>
        </div>
      </div>

      {/* Recipient Allowlists */}
      <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', padding: '16px', borderRadius: '10px' }}>
        <h4 style={{ fontSize: '0.82rem', color: 'var(--text-dim)', textTransform: 'uppercase', marginBottom: '8px', fontWeight: 600 }}>
          Recipient Address Allowlist:
        </h4>
        {policy.allowed_recipients && policy.allowed_recipients.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {policy.allowed_recipients.map((addr, i) => (
              <div key={i} className="font-mono" style={{ fontSize: '0.78rem', color: 'var(--color-cyan)', background: 'rgba(0, 0, 0, 0.25)', padding: '6px 10px', borderRadius: '6px' }}>
                {addr}
              </div>
            ))}
          </div>
        ) : (
          <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
            Permissive allowlist (any destination allowed subject to amount limits)
          </span>
        )}
      </div>

      {/* Editor Modal */}
      {showEditor && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.8)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '16px',
          }}
        >
          <div className="glass-panel" style={{ width: '100%', maxWidth: '520px', padding: '24px' }}>
            <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '6px' }}>
              Create New Policy Version
            </h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Incrementing the policy creates an immutable version snapshot (v{policy.version + 1}).
            </p>

            <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                  Max Amount per Transaction (ETH):
                </label>
                <input
                  type="number"
                  step="any"
                  value={maxEth}
                  onChange={(e) => setMaxEth(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-light)',
                    color: '#fff',
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                  Human Escalation Threshold (ETH):
                </label>
                <input
                  type="number"
                  step="any"
                  value={escalateEth}
                  onChange={(e) => setEscalateEth(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-light)',
                    color: '#fff',
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                  Daily Spending Budget (ETH):
                </label>
                <input
                  type="number"
                  step="any"
                  value={dailyEth}
                  onChange={(e) => setDailyEth(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-light)',
                    color: '#fff',
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', display: 'block', marginBottom: '4px' }}>
                  Allowed Recipients (one address per line):
                </label>
                <textarea
                  value={allowedInput}
                  onChange={(e) => setAllowedInput(e.target.value)}
                  rows={3}
                  className="font-mono"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-input)',
                    border: '1px solid var(--border-light)',
                    color: '#fff',
                    fontSize: '0.78rem',
                  }}
                />
              </div>

              {error && (
                <div style={{ color: '#fb7185', fontSize: '0.82rem', padding: '8px', background: 'rgba(244, 63, 94, 0.1)', borderRadius: '6px' }}>
                  {error}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button type="button" className="btn btn-outline" onClick={() => setShowEditor(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? 'Creating...' : `Publish Version ${policy.version + 1}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
