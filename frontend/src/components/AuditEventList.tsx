import { ChevronDown } from 'lucide-react';
import { humanizeEvent, presentAuditDetails } from '../auditPresentation.ts';
import type { AuditTrail } from '../types/index.ts';

export function AuditEventList({ events }: { events: AuditTrail['events'] }) {
  return <div className="audit-ledger" aria-label="Audit events">
    {events.map((event, index) => <details className="audit-ledger-event" key={event.id}>
      <summary>
        <span className="audit-ledger-index" aria-hidden="true">{index + 1}</span>
        <span className="audit-ledger-name">{humanizeEvent(event.event_type)}</span>
        <span className="audit-ledger-actor" title={event.actor}>{event.actor}</span>
        <time dateTime={event.created_at} title={new Date(event.created_at).toLocaleString()}
          aria-label={new Date(event.created_at).toLocaleString()}>{new Date(event.created_at).toLocaleTimeString()}</time>
        <ChevronDown size={15} className="audit-ledger-chevron" aria-hidden="true" />
      </summary>
      <div className="audit-ledger-details"><dl className="audit-facts">
        <dt>Recorded</dt><dd>{new Date(event.created_at).toLocaleString()}</dd>
        <dt>Event code</dt><dd>{event.event_type}</dd>
        <dt>Actor</dt><dd>{event.actor}</dd>
        {Object.entries(presentAuditDetails(event.details)).map(([key, value]) =>
          <div className="audit-ledger-fact" key={key}><dt>{humanizeEvent(key)}</dt>
            <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}
        <dt>Previous hash</dt><dd className="font-mono">{event.previous_hash || 'Genesis'}</dd>
        <dt>Event hash</dt><dd className="font-mono">{event.event_hash}</dd>
      </dl></div>
    </details>)}
  </div>;
}
