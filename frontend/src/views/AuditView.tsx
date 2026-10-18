import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.ts';
import { humanizeEvent, presentAuditDetails } from '../auditPresentation.ts';
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
        <div><h2>Audit integrity</h2><p>Check hash consistency across up to 200 recent records.</p></div>
        <button className="btn btn-outline" onClick={() => void verify()} disabled={verifying}>{verifying ? 'Checking…' : 'Verify chain'}</button>
      </div>
      {verificationError && <p className="audit-error" role="alert">{verificationError}</p>}
      {verification && <div className="audit-integrity-summary">
        <span className={verification.is_valid ? 'badge badge-allow' : 'badge badge-block'}>{verification.is_valid ? 'Chain check passed' : 'Chain check failed'}</span>
        <span>Requested limit: {verification.checked_limit} events</span>
      </div>}
      <p className="audit-note">Hash consistency does not independently authenticate the checkpoint or the recorded history.</p>
    </section>
    <section className="glass-panel audit-panel">
      <h2>Find audit events</h2>
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
      {trailError && <p className="audit-error" role="alert">{trailError}</p>}
      {trail && !trailLoading && <div>
        <p className="audit-note">{trail.events.length} events · {trail.chain_valid ? 'Chain check passed' : 'Chain check failed'}</p>
        {trail.events.length === 0 && <p>No audit events found for this reference.</p>}
        {trail.events.map((event) => <article className="audit-event" key={event.id}>
          <div className="audit-event-heading"><h3>{humanizeEvent(event.event_type)}</h3><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time></div>
          <p className="audit-note">Recorded by {event.actor}</p>
          <dl className="audit-facts">{Object.entries(presentAuditDetails(event.details)).map(([key, value]) =>
            <React.Fragment key={key}><dt>{humanizeEvent(key)}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></React.Fragment>)}</dl>
          <details className="audit-technical"><summary>Event hash</summary><p className="font-mono">{event.event_hash}</p></details>
        </article>)}
      </div>}
    </section>
  </div>;
};
