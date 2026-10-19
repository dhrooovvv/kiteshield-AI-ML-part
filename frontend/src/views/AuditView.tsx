import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.ts';
import { AuditEventList } from '../components/AuditEventList.tsx';
import type { AuditIntegrityVerification, AuditTrail } from '../types/index.ts';

export const AuditView: React.FC<{ refreshRevision: number }> = ({ refreshRevision }) => {
  const [correlationIdInput, setCorrelationIdInput] = useState('');
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [trailLoading, setTrailLoading] = useState(false);
  const [trailError, setTrailError] = useState<string | null>(null);
  const [verification, setVerification] = useState<AuditIntegrityVerification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const lastLookup = useRef('');
  const hasVerified = useRef(false);

  const loadTrail = useCallback(async (cid: string) => {
    setTrailLoading(true);
    setTrailError(null);
    try { setTrail(await api.getAuditTrail(cid)); }
    catch (err: unknown) {
      setTrail(null);
      setTrailError(err instanceof Error ? err.message : 'Unable to load audit events. Retry.');
    } finally { setTrailLoading(false); }
  }, []);

  const verify = useCallback(async () => {
    hasVerified.current = true;
    setVerifying(true);
    setVerificationError(null);
    setVerification(null);
    try { setVerification(await api.verifyAuditIntegrity(200)); }
    catch (err: unknown) { setVerificationError(err instanceof Error ? err.message : 'Unable to verify the chain. Retry.'); }
    finally { setVerifying(false); }
  }, []);

  useEffect(() => {
    if (lastLookup.current) void loadTrail(lastLookup.current);
    if (hasVerified.current) void verify();
  }, [refreshRevision, loadTrail, verify]);

  return <div className="audit-explorer">
    <section className="glass-panel audit-panel">
      <div className="section-heading-row">
        <h2>Audit events</h2>
        <button className="btn btn-outline" onClick={() => void verify()} disabled={verifying}>{verifying ? 'Checking…' : 'Verify chain'}</button>
      </div>
      {verificationError && <p className="audit-error" role="alert">{verificationError}</p>}
      {verification && <div className="audit-integrity-summary">
        <span className={verification.is_valid ? 'badge badge-allow' : 'badge badge-block'}>{verification.is_valid ? 'Chain check passed' : 'Chain check failed'}</span>
        <span>Limit: {verification.checked_limit} events</span>
      </div>}
      <details className="audit-scope"><summary>Verification scope</summary><p>Checks hash consistency across up to 200 recent records. This does not independently authenticate the checkpoint or recorded history.</p></details>
      <form className="audit-lookup" onSubmit={(event) => {
        event.preventDefault();
        const cid = correlationIdInput.trim();
        if (!cid) return;
        lastLookup.current = cid;
        void loadTrail(cid);
      }}>
        <label htmlFor="audit-reference">Request reference</label>
        <div><input id="audit-reference" value={correlationIdInput} onChange={(event) => setCorrelationIdInput(event.target.value)} placeholder="Enter a correlation ID" required />
          <button className="btn btn-outline" disabled={trailLoading}>{trailLoading ? 'Loading…' : 'Find events'}</button></div>
      </form>
      {trailLoading && <p role="status" className="audit-note">Loading events…</p>}
      {trailError && <p className="audit-error" role="alert">{trailError}</p>}
      {trail && !trailLoading && <div>
        <p className="audit-note">{trail.events.length} events · {trail.chain_valid ? 'Chain check passed' : 'Chain check failed'}</p>
        {trail.events.length === 0 && <p>No audit events found for this reference.</p>}
        <AuditEventList events={trail.events} />
      </div>}
    </section>
  </div>;
};
