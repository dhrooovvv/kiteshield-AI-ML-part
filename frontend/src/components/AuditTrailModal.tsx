import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api/client.ts';
import type { AuditTrail } from '../types/index.ts';
import { presentAuditDetails, humanizeEvent } from '../auditPresentation.ts';

interface AuditTrailModalProps {
  correlationId: string;
  onClose: () => void;
}

export const AuditTrailModal: React.FC<AuditTrailModalProps> = ({ correlationId, onClose }) => {
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement;
    dialog.current?.showModal();
    return () => { if (previousFocus instanceof HTMLElement) previousFocus.focus(); };
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) { setLoading(true); setError(null); }
    });
    api.getAuditTrail(correlationId).then((data) => {
      if (active) setTrail(data);
    }).catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : 'Unable to load audit events. Try refreshing.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [correlationId, revision]);

  return createPortal(
    <dialog ref={dialog} className="audit-dialog" aria-labelledby="audit-dialog-title" onCancel={onClose}>
      <header className="audit-dialog-heading">
        <div>
          <h2 id="audit-dialog-title">Audit trail</h2>
          <p>Request reference <span className="font-mono">{correlationId}</span></p>
        </div>
        <button className="btn btn-outline" onClick={() => setRevision((value) => value + 1)} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>
      <div className="audit-dialog-body" aria-busy={loading}>
        {loading && <p role="status">Loading audit events…</p>}
        {error && <p className="audit-error" role="alert">{error}</p>}
        {trail && !loading && !error && <>
          <div className="audit-integrity-summary">
            <span className={trail.chain_valid ? 'badge badge-allow' : 'badge badge-block'}>
              {trail.chain_valid ? 'Chain check passed' : 'Chain check failed'}
            </span>
            <span>{trail.events.length} events</span>
          </div>
          <p className="audit-note">This checks stored hash consistency. It does not independently authenticate the recorded history.</p>
          {trail.events.length === 0 && <p>No audit events were found for this request.</p>}
          {trail.events.map((event) => <article key={event.id} className="audit-event">
            <div className="audit-event-heading">
              <h3>{humanizeEvent(event.event_type)}</h3>
              <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time>
            </div>
            <p className="audit-note">Recorded by {event.actor}</p>
            <dl className="audit-facts">
              {Object.entries(presentAuditDetails(event.details)).map(([key, value]) =>
                <React.Fragment key={key}><dt>{humanizeEvent(key)}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></React.Fragment>
              )}
            </dl>
            <details className="audit-technical">
              <summary>Technical details</summary>
              <dl className="audit-facts"><dt>Previous hash</dt><dd className="font-mono">{event.previous_hash || 'Genesis'}</dd>
                <dt>Event hash</dt><dd className="font-mono">{event.event_hash}</dd></dl>
            </details>
          </article>)}
        </>}
      </div>
      <footer className="audit-dialog-footer"><button className="btn btn-outline" onClick={onClose}>Close</button></footer>
    </dialog>, document.body
  );
};
